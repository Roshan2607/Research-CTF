"""Sign in with ChatGPT (local app flow): OAuth 2.0 authorization code + PKCE, dynamic client registration.

Follows OpenAI's published "Sign in with ChatGPT" open-source local-app flow. No developer API key and no
client secret: the organiser signs in once in their own browser, and the judge then spends their ChatGPT plan
allowance. Requires a plan that supports it (Plus/Pro per OpenAI's docs).

What is documented vs. inferred
* Documented: authorize URL, token URL, scopes, ``resource``, loopback redirect rules, S256 PKCE, dynamic
  registration via ``client_id=dynamic_agent_client`` + ``ext_agent_host_id``, id_token claim checks.
* Inferred (not on the pages I could read): the refresh request. It is implemented as the standard OAuth
  ``grant_type=refresh_token`` POST to the same token endpoint. If OpenAI documents otherwise, change ``refresh``.

Credentials live in ``~/.pot-judge/chatgpt-auth.json`` (mode 0600), outside the repo, and are never logged.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import uuid
import webbrowser
from pathlib import Path
from typing import Callable

AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
REQUIRED_SCOPE = "chatgpt.tokens.use.direct"
CALLBACK_PORT = 1455
CALLBACK_PATH = "/auth/callback"
APP_NAME = "Proof of Thought judge"
REFRESH_MARGIN = 120  # seconds before expiry at which we refresh


class AuthError(RuntimeError):
    pass


def store_dir() -> Path:
    return Path(os.environ.get("POT_JUDGE_HOME") or (Path.home() / ".pot-judge"))


def _write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def host_id() -> str:
    p = store_dir() / "chatgpt-host.json"
    if p.exists():
        return json.loads(p.read_text())["host_id"]
    hid = f"urn:uuid:{uuid.uuid4()}"
    _write_private(p, {"host_id": hid})
    return hid


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(48))
    return verifier, _b64url(hashlib.sha256(verifier.encode()).digest())


def redirect_uri(port: int = CALLBACK_PORT) -> str:
    return f"http://127.0.0.1:{port}{CALLBACK_PATH}"  # must be 127.0.0.1, never "localhost"


def build_authorize_url(client_id: str, state: str, nonce: str, challenge: str, port: int = CALLBACK_PORT,
                        first_registration: bool = True, hint_host: str | None = None) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(port),
        "scope": SCOPE,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "ext_agent_host_id": hint_host or host_id(),
    }
    if first_registration:
        params["agent_name_hint"] = APP_NAME
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def _jwt_claims(token: str) -> dict:
    """Decode (not signature-verify) a JWT. OIDC Core 3.1.3.7 allows skipping signature verification for an
    ID token received directly from the token endpoint over TLS, which is the only way we obtain it."""
    try:
        body = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception as exc:  # noqa: BLE001
        raise AuthError("malformed id_token") from exc


def validate_id_token(id_token: str, client_id: str, nonce: str, now: float | None = None) -> dict:
    c = _jwt_claims(id_token)
    aud = c.get("aud")
    if client_id not in (aud if isinstance(aud, list) else [aud]):
        raise AuthError("id_token audience does not match the issued client_id")
    if c.get("nonce") != nonce:
        raise AuthError("id_token nonce mismatch")
    if float(c.get("exp", 0)) <= (now if now is not None else time.time()):
        raise AuthError("id_token expired")
    if not c.get("sub"):
        raise AuthError("id_token has no subject")
    return c


def check_callback(query: dict, expected_state: str, first_registration: bool, known_client_id: str | None) -> tuple[str, str]:
    """Validate the loopback callback. Returns (code, client_id)."""
    q = {k: v[0] for k, v in query.items()}
    if q.get("state") != expected_state:
        raise AuthError("state mismatch; callback rejected")
    if q.get("error"):
        raise AuthError(f"authorization failed: {q['error']}")
    if not q.get("code"):
        raise AuthError("callback carried no authorization code")
    client_id = q.get("client_id") or known_client_id
    if first_registration and not q.get("client_id"):
        raise AuthError("new registration returned no issued client_id")
    if known_client_id and q.get("client_id") and q["client_id"] != known_client_id:
        raise AuthError("callback client_id differs from the saved one")
    return q["code"], client_id


def _post_form(url: str, data: dict) -> dict:
    import requests

    r = requests.post(url, data=data, timeout=20)
    if r.status_code >= 400:
        try:
            err = r.json().get("error", "")
        except ValueError:
            err = ""
        raise AuthError(f"token endpoint returned {r.status_code} {err}".strip())
    return r.json()


def exchange_code(code: str, verifier: str, client_id: str, port: int = CALLBACK_PORT,
                  post: Callable[[str, dict], dict] = _post_form) -> dict:
    return post(TOKEN_URL, {
        "grant_type": "authorization_code", "client_id": client_id, "code": code,
        "code_verifier": verifier, "redirect_uri": redirect_uri(port), "resource": RESOURCE,
    })


def login(open_browser: Callable[[str], object] = webbrowser.open, timeout: float = 300.0,
          post: Callable[[str, dict], dict] = _post_form, port: int = CALLBACK_PORT) -> dict:
    """Interactive sign-in. The person signs in in their own browser; this only receives the callback."""
    creds_path = store_dir() / "chatgpt-auth.json"
    known = json.loads(creds_path.read_text()) if creds_path.exists() else {}
    known_client = known.get("client_id")
    first = not known_client
    state, nonce = _b64url(secrets.token_bytes(24)), _b64url(secrets.token_bytes(24))
    verifier, challenge = make_pkce()

    result: dict = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_response(404); self.end_headers(); return
            result["query"] = urllib.parse.parse_qs(parsed.query)
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
            self.wfile.write(b"Signed in. You can close this tab and return to the terminal.")
            done.set()

        def log_message(self, *a):  # keep codes/state out of the console
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)  # listener first, then the browser
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = build_authorize_url(known_client or "dynamic_agent_client", state, nonce, challenge, port, first)
        open_browser(url)
        if not done.wait(timeout):
            raise AuthError("timed out waiting for sign-in")
    finally:
        server.shutdown()

    code, client_id = check_callback(result["query"], state, first, known_client)
    tokens = exchange_code(code, verifier, client_id, port, post)
    claims = validate_id_token(tokens.get("id_token", ""), client_id, nonce)
    scopes = tokens.get("scopes") or tokens.get("scope") or ""
    scopes = scopes.split() if isinstance(scopes, str) else list(scopes)
    if REQUIRED_SCOPE not in scopes:
        raise AuthError(f"sign-in succeeded but {REQUIRED_SCOPE} was not granted; ChatGPT plan usage is unavailable")
    creds = {
        "email": claims.get("email", ""), "issuer": claims.get("iss", ""), "subject": claims["sub"],
        "client_id": client_id, "ext_agent_host_id": host_id(),
        "id_token": tokens["id_token"], "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""), "token_type": tokens.get("token_type", "Bearer"),
        "expires_in": tokens.get("expires_in", 3600), "scopes": scopes, "saved_at": time.time(),
    }
    _write_private(creds_path, creds)
    return {k: creds[k] for k in ("email", "subject", "client_id", "scopes")}


# ---------------------------------------------------------------------- using saved credentials
def load_creds() -> dict:
    p = store_dir() / "chatgpt-auth.json"
    if not p.exists():
        raise AuthError("not signed in: run  python scripts/chatgpt_login.py")
    return json.loads(p.read_text())


def refresh(creds: dict, post: Callable[[str, dict], dict] = _post_form) -> dict:
    """Standard OAuth refresh (INFERRED; see module docstring). Replaces access + rotating refresh token."""
    if not creds.get("refresh_token"):
        raise AuthError("no refresh token saved; sign in again")
    tokens = post(TOKEN_URL, {"grant_type": "refresh_token", "client_id": creds["client_id"],
                              "refresh_token": creds["refresh_token"], "resource": RESOURCE})
    creds = dict(creds)
    creds.update(access_token=tokens["access_token"], saved_at=time.time(),
                 expires_in=tokens.get("expires_in", creds.get("expires_in", 3600)),
                 refresh_token=tokens.get("refresh_token", creds["refresh_token"]))
    if tokens.get("id_token"):
        creds["id_token"] = tokens["id_token"]
    scopes = tokens.get("scopes") or tokens.get("scope")
    if scopes:
        creds["scopes"] = scopes.split() if isinstance(scopes, str) else list(scopes)
        if REQUIRED_SCOPE not in creds["scopes"]:
            raise AuthError(f"{REQUIRED_SCOPE} no longer granted; sign in again")
    _write_private(store_dir() / "chatgpt-auth.json", creds)
    return creds


_lock = threading.Lock()


def get_access_token(post: Callable[[str, dict], dict] = _post_form, now: Callable[[], float] = time.time) -> str:
    """A valid access token, refreshing shortly before expiry. Thread-safe (the worker and tests share it)."""
    with _lock:
        creds = load_creds()
        if now() >= creds["saved_at"] + float(creds.get("expires_in", 3600)) - REFRESH_MARGIN:
            creds = refresh(creds, post)
        return creds["access_token"]
