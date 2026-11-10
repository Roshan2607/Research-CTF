"""Sign in with ChatGPT: PKCE, authorize URL, callback and id_token checks, credential storage, refresh,
and the streaming Responses judge. No network: HTTP and the OpenAI client are faked."""
import base64
import hashlib
import json
import os
import stat
import time
import threading
import urllib.parse
import urllib.request
from types import SimpleNamespace

import pytest

from judging import chatgpt_auth as A
from judging.chatgpt_judge import ChatGPTError, ChatGPTJudge, parse_verdict_json
from judging.store import EdgeRow


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("POT_JUDGE_HOME", str(tmp_path / "pj"))


def jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'RS256'})}.{enc(claims)}.sig"


def test_pkce_challenge_is_s256_of_verifier():
    v, c = A.make_pkce()
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert 43 <= len(v) <= 128 and "=" not in v


def test_authorize_url_matches_the_documented_shape():
    url = A.build_authorize_url("dynamic_agent_client", "st", "no", "ch")
    u = urllib.parse.urlparse(url)
    q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    assert f"{u.scheme}://{u.netloc}{u.path}" == "https://auth.openai.com/api/accounts/authorize"
    assert q["client_id"] == "dynamic_agent_client" and q["agent_name_hint"] and q["ext_agent_host_id"].startswith("urn:uuid:")
    assert q["redirect_uri"] == "http://127.0.0.1:1455/auth/callback" and "localhost" not in url
    assert q["code_challenge_method"] == "S256" and q["resource"] == "https://api.openai.com/v1"
    assert "chatgpt.tokens.use.direct" in q["scope"].split() and "offline_access" in q["scope"].split()
    again = A.build_authorize_url("oaiapp_x", "s", "n", "c", first_registration=False)
    assert "agent_name_hint" not in again  # only on first registration


def test_host_id_is_stable_and_private():
    a, b = A.host_id(), A.host_id()
    assert a == b
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(A.store_dir() / "chatgpt-host.json").st_mode) == 0o600


def test_callback_checks():
    ok = {"state": ["s"], "code": ["c"], "client_id": ["oaiapp_1"]}
    assert A.check_callback(ok, "s", True, None) == ("c", "oaiapp_1")
    with pytest.raises(A.AuthError, match="state"):
        A.check_callback({**ok, "state": ["evil"]}, "s", True, None)
    with pytest.raises(A.AuthError, match="authorization failed"):
        A.check_callback({"state": ["s"], "error": ["access_denied"]}, "s", True, None)
    with pytest.raises(A.AuthError, match="no issued client_id"):
        A.check_callback({"state": ["s"], "code": ["c"]}, "s", True, None)
    with pytest.raises(A.AuthError, match="differs"):
        A.check_callback(ok, "s", False, "oaiapp_other")
    assert A.check_callback({"state": ["s"], "code": ["c"]}, "s", False, "oaiapp_1")[1] == "oaiapp_1"


def test_id_token_validation():
    good = jwt({"aud": "oaiapp_1", "nonce": "n", "exp": time.time() + 60, "sub": "u1"})
    assert A.validate_id_token(good, "oaiapp_1", "n")["sub"] == "u1"
    for claims, msg in [({"aud": "other", "nonce": "n", "exp": time.time() + 60, "sub": "u"}, "audience"),
                        ({"aud": "oaiapp_1", "nonce": "x", "exp": time.time() + 60, "sub": "u"}, "nonce"),
                        ({"aud": "oaiapp_1", "nonce": "n", "exp": time.time() - 5, "sub": "u"}, "expired")]:
        with pytest.raises(A.AuthError, match=msg):
            A.validate_id_token(jwt(claims), "oaiapp_1", "n")


def test_login_end_to_end_with_fake_browser_and_token_endpoint():
    holder = {}

    def fake_browser(url):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        holder["nonce"] = q["nonce"][0]
        def hit():
            time.sleep(0.2)
            urllib.request.urlopen("http://127.0.0.1:%d/auth/callback?code=CODE&state=%s&client_id=oaiapp_1"
                                   % (A.CALLBACK_PORT + 1, q["state"][0])).read()
        threading.Thread(target=hit).start()

    def fake_post(url, data):
        assert url == A.TOKEN_URL and data["code"] == "CODE" and data["client_id"] == "oaiapp_1" and data["code_verifier"]
        return {"id_token": jwt({"aud": "oaiapp_1", "nonce": holder["nonce"], "exp": time.time() + 600,
                                 "sub": "u1", "email": "o@example.com", "iss": "https://auth.openai.com"}),
                "access_token": "AT", "refresh_token": "RT", "expires_in": 3600,
                "scopes": "openid chatgpt.tokens.use.direct"}

    info = A.login(open_browser=fake_browser, post=fake_post, port=A.CALLBACK_PORT + 1, timeout=10)
    assert info["client_id"] == "oaiapp_1"
    path = A.store_dir() / "chatgpt-auth.json"
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert json.loads(path.read_text())["access_token"] == "AT"


def test_missing_plan_scope_is_rejected():
    creds = {"client_id": "c", "refresh_token": "r", "expires_in": 3600, "saved_at": time.time(), "scopes": []}
    A._write_private(A.store_dir() / "chatgpt-auth.json", creds)
    with pytest.raises(A.AuthError, match="no longer granted"):
        A.refresh(creds, post=lambda u, d: {"access_token": "x", "scopes": "openid"})


def test_token_refreshes_near_expiry_and_rotates():
    now = time.time()
    A._write_private(A.store_dir() / "chatgpt-auth.json", {
        "client_id": "c", "access_token": "OLD", "refresh_token": "R1", "expires_in": 3600,
        "saved_at": now - 3590, "scopes": ["chatgpt.tokens.use.direct"]})
    calls = []
    post = lambda u, d: calls.append(d) or {"access_token": "NEW", "refresh_token": "R2", "expires_in": 3600}  # noqa: E731
    assert A.get_access_token(post=post) == "NEW" and calls[0]["grant_type"] == "refresh_token"
    assert A.load_creds()["refresh_token"] == "R2"
    assert A.get_access_token(post=post) == "NEW" and len(calls) == 1  # fresh now: no second refresh


def test_not_signed_in_is_a_clear_fatal_error():
    from judging.worker import is_fatal

    with pytest.raises(A.AuthError) as e:
        A.load_creds()
    assert is_fatal(e.value)


# ---------------------------------------------------------------- judge
def ev(kind, **kw):
    return SimpleNamespace(type=kind, **kw)


def client_streaming(events, seen):
    def create(**kw):
        seen.update(kw)
        return iter(events)
    return SimpleNamespace(responses=SimpleNamespace(create=create))


def judge_with(events, seen=None):
    seen = {} if seen is None else seen
    return ChatGPTJudge(model="m", token_provider=lambda: "TOKEN", client_factory=lambda t: client_streaming(events, seen)), seen


def edge(i):
    return EdgeRow(f"h{i}", "P02", "P05", "SHARES_PRINCIPLE", "")


def test_streaming_judge_sends_required_flags_and_parses_json():
    body = json.dumps({"verdicts": [{"id": "e1", "verdict": "plausible", "reason": "partial"}]})
    events = [ev("response.output_text.delta", delta=body[:20]), ev("response.output_text.delta", delta=body[20:]),
              ev("response.completed")]
    j, seen = judge_with(events)
    out = j.judge_batch([edge(1)])
    assert out["h1"].verdict == "plausible"
    assert seen["store"] is False and seen["stream"] is True and seen["model"] == "m"
    assert seen["input"][0]["role"] == "system"


def test_stream_without_completed_is_a_failure():
    j, _ = judge_with([ev("response.output_text.delta", delta="{}")])
    with pytest.raises(ChatGPTError, match="completed"):
        j.judge_batch([edge(1)])


def test_usage_limit_error_is_fatal_for_the_worker():
    from judging.worker import is_fatal

    fail = ev("response.failed", response=SimpleNamespace(error=SimpleNamespace(code="subscription_sharing_usage_limit_exceeded")))
    j, _ = judge_with([fail])
    with pytest.raises(ChatGPTError) as e:
        j.judge_batch([edge(1)])
    assert is_fatal(e.value)


def test_json_parser_tolerates_fences_and_rejects_junk():
    assert parse_verdict_json('```json\n{"verdicts":[{"id":"e1","verdict":"supported","reason":"r"}]}\n```')["e1"][0] == "supported"
    assert parse_verdict_json("no json here") == {} and parse_verdict_json("{broken") == {}


def test_default_model_is_terra_when_available_else_first_listed(monkeypatch):
    from judging import chatgpt_judge as cj

    j = ChatGPTJudge(token_provider=lambda: "T")
    monkeypatch.setattr(j, "list_models", lambda: [{"slug": "other"}, {"slug": cj.DEFAULT_MODEL}])
    assert j._resolve_model() == "gpt-6.1-terra"
    j2 = ChatGPTJudge(token_provider=lambda: "T")
    monkeypatch.setattr(j2, "list_models", lambda: [{"slug": "other"}])
    assert j2._resolve_model() == "other"
    assert ChatGPTJudge(model="pinned", token_provider=lambda: "T")._resolve_model() == "pinned"
