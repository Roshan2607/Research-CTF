"""Participant portal for the incremental multi-cluster graph challenge."""
import html
import io
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

try:
    import extra_streamlit_components as stx
except ImportError:
    class DummyCookieManager:
        def __init__(self, key=None):
            pass
        def get_all(self):
            return {}
        def get(self, key):
            return None
        def set(self, key, value, expires_at=None):
            pass
        def delete(self, key):
            pass

    class _MockStx:
        CookieManager = DummyCookieManager

    stx = _MockStx()

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from challenge.participant_data import card_pdf_path, load_corpus, load_vocabulary
from scripts.evaluate_submissions import evaluate_submission, EvaluationDetail
from event_core import (
    CLUSTER,
    LEVELS,
    _content,
    attempt_flag,
    final_results_visible,
    hint_status,
    open_level,
    reveal_hint,
    authenticate,
    authenticate_session,
    clusters,
    create_session,
    create_team,
    finalise,
    flag_status,
    get_draft,
    get_live_judge,
    levels_for_cluster,
    load,
    next_available_team_id,
    released_papers,
    revoke_session,
    save_draft,
    team_progress,
    verification_status,
    record_verification,
    parse_uploaded_graph_csv,
    safe_csv,
    level_points,
    google_form_url,
    load_demo_level0,
)

st.set_page_config(page_title="Proof of Thought · Participant", layout="wide")

st.markdown("""
<style>
[data-testid="stMetricValue"] {
    white-space: normal !important;
    word-break: break-word !important;
    overflow-wrap: break-word !important;
}
[data-testid="stMetricDelta"] {
    white-space: normal !important;
    word-break: break-word !important;
}

/* Eliminate top dead space so page and navbar start immediately at top next to sidebar */
.block-container {
    padding-top: 1rem !important;
    padding-bottom: 2rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 96% !important;
}

header[data-testid="stHeader"] {
    background-color: transparent !important;
    height: 1.5rem !important;
    z-index: 1;
}

/* Full-Width Modern Top Segmented Control Navbar */
div[data-testid="stElementContainer"],
div.element-container,
div[data-testid="stElementContainer"]:has(div[data-testid="stRadio"]),
div.element-container:has(div.stRadio) {
    width: 100% !important;
    max-width: 100% !important;
}

div.stRadio,
div[data-testid="stRadio"] {
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
    display: block !important;
    box-sizing: border-box !important;
    margin-top: 0 !important;
    margin-bottom: 1.5rem !important;
}

div[data-testid="stRadioGroup"],
div[role="radiogroup"] {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    justify-content: stretch !important;
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
    height: 48px !important;
    min-height: 48px !important;
    max-height: 48px !important;
    background: #0d1117 !important;
    padding: 4px !important;
    border-radius: 10px !important;
    border: 1px solid #30363d !important;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35) !important;
    box-sizing: border-box !important;
    gap: 6px !important;
    overflow: hidden !important;
}

div[role="radiogroup"] label[data-baseweb="radio"],
div[data-testid="stRadio"] label[data-baseweb="radio"] {
    flex: 1 1 0px !important;
    min-width: 0 !important;
    width: auto !important;
    max-width: 100% !important;
    height: 38px !important;
    min-height: 38px !important;
    max-height: 38px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    background-color: transparent !important;
    padding: 0 12px !important;
    margin: 0 !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    border-radius: 6px !important;
    cursor: pointer !important;
    border: 1px solid transparent !important;
    box-sizing: border-box !important;
    transition: all 0.15s ease-in-out !important;
    overflow: hidden !important;
}

div[role="radiogroup"] label[data-baseweb="radio"]:hover,
div[data-testid="stRadio"] label[data-baseweb="radio"]:hover {
    background-color: #21262d !important;
}

div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked),
div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
    background-color: #1f6feb !important;
    border: 1px solid #388bfd !important;
    box-shadow: 0 1px 4px rgba(31, 111, 235, 0.45) !important;
}

div[role="radiogroup"] label[data-baseweb="radio"] > div:first-of-type,
div[role="radiogroup"] label[data-baseweb="radio"] input[type="radio"],
div[data-testid="stRadio"] label[data-baseweb="radio"] > div:first-of-type,
div[data-testid="stRadio"] label[data-baseweb="radio"] input[type="radio"] {
    display: none !important;
}

div[role="radiogroup"] label[data-baseweb="radio"] div:last-child,
div[role="radiogroup"] label[data-baseweb="radio"] p,
div[role="radiogroup"] label[data-baseweb="radio"] span,
div[data-testid="stRadio"] label[data-baseweb="radio"] div:last-child,
div[data-testid="stRadio"] label[data-baseweb="radio"] p,
div[data-testid="stRadio"] label[data-baseweb="radio"] span {
    font-size: 0.95rem !important;
    font-weight: 500 !important;
    color: #8b949e !important;
    margin: 0 !important;
    padding: 0 !important;
    line-height: normal !important;
    transition: color 0.15s ease !important;
    text-align: center !important;
    width: auto !important;
    white-space: nowrap !important;
    word-break: normal !important;
    overflow-wrap: normal !important;
}

div[role="radiogroup"] label[data-baseweb="radio"]:hover div:last-child,
div[role="radiogroup"] label[data-baseweb="radio"]:hover p,
div[data-testid="stRadio"] label[data-baseweb="radio"]:hover div:last-child,
div[data-testid="stRadio"] label[data-baseweb="radio"]:hover p {
    color: #e6edf3 !important;
}

div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked) div:last-child,
div[role="radiogroup"] label[data-baseweb="radio"]:has(input:checked) p,
div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) div:last-child,
div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) p {
    color: #ffffff !important;
    font-weight: 600 !important;
}
</style>
""", unsafe_allow_html=True)

cookie_manager = stx.CookieManager(key="ul_participant_cookie")
cookies = cookie_manager.get_all()
if cookies is None:
    st.info("Restoring participant session…")
    st.stop()


def login():
    st.subheader("Participant Login")
    tab_login, tab_register = st.tabs(["Sign in to Existing Team", "Register New Team (FCFS)"])

    with tab_login:
        with st.form("login"):
            tid = st.text_input("Team ID")
            pw = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", type="primary")
        if ok:
            user = authenticate(tid, pw)
            if user:
                token = create_session(user["team_id"])
                try:
                    cookie_manager.set("ul_team_session", token, expires_at=datetime.now() + timedelta(days=14))
                except Exception:
                    pass
                st.query_params["session"] = token
                st.session_state["event_team"] = user
                st.rerun()
            else:
                st.error("Invalid team ID or password.")

    with tab_register:
        suggested_id = next_available_team_id()
        st.info(f"Assigned Team ID: **{suggested_id}** (First-Come, First-Served)")
        with st.form("claim_team"):
            new_name = st.text_input("Team Name", placeholder="e.g. Neural Ninjas", key="claim_name")
            new_pw = st.text_input(
                "Team Password (min 8 chars)",
                type="password",
                key="claim_pw",
                help="Save this password! Your teammates will need this password and your Team ID to sign in from their devices.",
            )
            new_pw_conf = st.text_input("Confirm Password", type="password", key="claim_pw_conf")
            claim_btn = st.form_submit_button("Claim Team & Enter Event", type="primary")

        if claim_btn:
            if not new_name.strip():
                st.error("Please enter a team name.")
            elif len(new_pw) < 8:
                st.error("Password must be at least 8 characters.")
            elif new_pw != new_pw_conf:
                st.error("Passwords do not match.")
            else:
                avail = clusters()
                assign_cluster = avail[0] if avail else CLUSTER
                try:
                    assigned_id = create_team(suggested_id, new_name.strip(), new_pw, cluster=assign_cluster)
                    user = authenticate(assigned_id, new_pw)
                    if user:
                        token = create_session(user["team_id"])
                        try:
                            cookie_manager.set("ul_team_session", token, expires_at=datetime.now() + timedelta(days=14))
                        except Exception:
                            pass
                        st.query_params["session"] = token
                        st.session_state["event_team"] = user
                        st.session_state["created_team_alert"] = {
                            "id": assigned_id,
                            "name": new_name.strip(),
                            "password": new_pw,
                        }
                        st.rerun()
                except ValueError as e:
                    st.error(str(e))


team = st.session_state.get("event_team")
if not team:
    token = (
        st.query_params.get("session")
        or (cookies.get("ul_team_session") if isinstance(cookies, dict) else None)
        or cookie_manager.get("ul_team_session")
    )
    if token:
        team = authenticate_session(token)
        if team:
            st.session_state["event_team"] = team
            st.query_params["session"] = token

if not team:
    login()
    st.stop()
else:
    # Keep session query parameter in sync so page refreshes and new tabs stay logged in
    curr_token = (
        st.query_params.get("session")
        or (cookies.get("ul_team_session") if isinstance(cookies, dict) else None)
        or cookie_manager.get("ul_team_session")
    )
    if curr_token and st.query_params.get("session") != curr_token:
        st.query_params["session"] = curr_token

# Persistent registration confirmation notice for participants
created_alert = st.session_state.get("created_team_alert")
if created_alert:
    col_a1, col_a2 = st.columns([5, 1])
    with col_a1:
        st.success(
            f"Team `{created_alert['id']}` (**{created_alert['name']}**) registered successfully!\n\n"
            f"• **Team ID**: `{created_alert['id']}`\n\n"
            f"• **Initial Password**: `{created_alert['password']}`\n\n"
            f"Share these credentials with your teammates so they can sign in from their devices."
        )
    with col_a2:
        if st.button("Dismiss", key="dismiss_created_team_alert"):
            st.session_state.pop("created_team_alert", None)
            st.rerun()

team_levels = levels_for_cluster(team["cluster"])
completed, current = team_progress(team["team_id"])

with st.sidebar:
    st.markdown(f"**Proof of Thought** · `{team['name']}` ({team['team_id']})")
    if team.get("is_demo"):
        st.info("Demo Team (Level 0)")
    st.markdown("### Level progress")
    d_sidebar = load()
    sidebar_total_pts = 0.0
    for lv in team_levels:
        rec = d_sidebar.get("submissions", {}).get(f"{team['team_id']}:{lv['id']}")
        if lv["id"] in completed:
            if lv["id"] == 0:
                st.markdown(f":gray[[Completed] Level 0: {lv['title']} (Practice)]")
            elif rec:
                fp = rec.get("flag_points", 0)
                gp = rec.get("graph_score", {}).get("points", 0) + rec.get("manual_adjustment", 0)
                tot_lp = int(round(fp + gp))
                sidebar_total_pts += tot_lp
                st.markdown(f":gray[[Completed] Level {lv['id']}: {lv['title']} — **{tot_lp:,d} pts**]")
            else:
                st.markdown(f":gray[[Completed] Level {lv['id']}: {lv['title']}]")
        elif lv["id"] == current:
            st.markdown(f":orange[**[Current] Level {lv['id']}: {lv['title']}**]")
        else:
            st.markdown(f":red[[Locked] Level {lv['id']}: {lv['title']}]")

    if sidebar_total_pts > 0:
        st.divider()
        st.metric("Total Score", f"{int(round(sidebar_total_pts)):,d} pts")
    if st.button("Sign out"):
        token_to_revoke = (
            st.query_params.get("session")
            or (cookies.get("ul_team_session") if isinstance(cookies, dict) else None)
            or cookie_manager.get("ul_team_session")
        )
        if token_to_revoke:
            revoke_session(token_to_revoke)
        try:
            cookie_manager.delete("ul_team_session")
        except (KeyError, Exception):
            pass
        st.query_params.clear()
        st.session_state.pop("event_team", None)
        st.rerun()

def render_graph_diagram(df: pd.DataFrame, available: list | None = None, byid: dict | None = None) -> None:
    """Render a clean Graphviz diagram from an edge dataframe with constrained dimensions."""
    byid = byid or {}
    node_set = list(available) if available else []
    if df is not None and not df.empty:
        for pid in sorted(set(df["source_id"].dropna().unique()) | set(df["target_id"].dropna().unique())):
            if pid not in node_set:
                node_set.append(pid)

    if not node_set:
        st.info("No papers released yet to display in graph.")
        return

    # Keep diagram compact so it never takes up the entire vertical viewport
    graph_size = 'size="5,1.8!"' if len(node_set) <= 2 else ('size="7,2.8!"' if len(node_set) <= 6 else 'size="9,4.2!"')
    dot = [
        f'digraph G {{ graph [rankdir=LR, bgcolor="#ffffff", pad="0.2", {graph_size}, ratio=compress]; ',
        'node [shape=box, style="rounded,filled", fillcolor="#EAF2FF", color="#315A8A", fontcolor="#142B45", fontname="Arial", fontsize=10, penwidth=1.5]; ',
        'edge [color="#2563EB", fontcolor="#173F7A", fontname="Arial", fontsize=9, penwidth=2, arrowsize=0.8];'
    ]

    import textwrap
    for pid in node_set:
        clean_pid = re.sub(r'[^A-Za-z0-9_]', '', str(pid).strip().upper())
        title = byid.get(pid, {}).get("title", "") if pid in byid else ""
        clean_title = re.sub(r'["\\\r\n]', ' ', str(title)).strip()
        if clean_title:
            wrapped = textwrap.wrap(clean_title, width=22, max_lines=3, placeholder="...")
            wrapped_str = "\\n".join(wrapped)
            lbl = f"{clean_pid}\\n{wrapped_str}"
        else:
            lbl = clean_pid
        dot.append(f'"{clean_pid}" [label="{lbl}"];')

    if df is not None and not df.empty:
        for _, r in df.iterrows():
            clean_s = re.sub(r'[^A-Za-z0-9_]', '', str(r.get("source_id", "")).strip().upper())
            clean_t = re.sub(r'[^A-Za-z0-9_]', '', str(r.get("target_id", "")).strip().upper())
            clean_rel = re.sub(r'[^A-Za-z0-9_]', '', str(r.get("relationship_type", "")).strip())
            style = "dir=none" if clean_rel in ("SHARES_PRINCIPLE", "ANALOGOUS_PROBLEM") else "dir=forward"
            if clean_s and clean_t:
                dot.append(f'"{clean_s}" -> "{clean_t}" [label=" {clean_rel} ", {style}];')

    dot.append("}")
    st.graphviz_chart("\n".join(dot), use_container_width=True)


def render_live_verification_card(detail: EvaluationDetail) -> None:
    st.markdown("---")
    st.markdown(f"#### Live Graph Verification Result · Level {detail.level}")

    if getattr(detail, "judge_error", ""):
        st.warning(f"• **Notice**: {detail.judge_error}")

    if detail.level == 0:
        c1, c2, c3 = st.columns(3)
        c1.metric("Practice Connection", f"{len(detail.correct_edges)} of {detail.total_reference_count} verified")
        c2.metric("Practice Status", "Passed" if detail.correct_edges else "Needs Connection")
        c3.metric("Warm-Up Points", "Unscored", "Practice Level")

        if detail.correct_edges:
            st.success(
                f"Practice relationship verified! ({detail.accuracy_pct:.0f}% match). "
                f"L0A and L0B share prefix/trie structures. Head to the Submit tab to complete the warm-up and unlock Level 1."
            )
        else:
            st.warning("Connect L0A and L0B (e.g. SHARES_PRINCIPLE) to verify the shared trie/prefix tree structure.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Benchmark Matches", f"{len(detail.correct_edges)} of {detail.total_reference_count} edges")
        c2.metric("Graph Accuracy", f"{detail.accuracy_pct:.1f}%")
        c3.metric(
            "Estimated Graph Points",
            f"{int(round(detail.final_graph_points)):,d} / {int(round(detail.max_graph_points)):,d} pts",
        )

        if detail.final_graph_points > 0:
            st.success(
                f"Verified! You have correctly connected {len(detail.correct_edges)} benchmark literature relationship(s) "
                f"and are on track to earn {detail.final_graph_points:g} graph points for this level."
            )
        elif detail.correct_edges and detail.final_graph_points == 0:
            st.warning(
                f"You matched {len(detail.correct_edges)} benchmark relationship(s), but penalties "
                f"(-{detail.decoy_penalty:g} decoy, -{detail.injection_penalty:g} injection) reduced graph points to 0. "
                "Remove decoy connections to restore your points."
            )
        else:
            st.warning("No benchmark relationships matched yet. Review the released papers and connect valid relationships to earn graph points.")

    with st.expander("Detailed Verification Breakdown", expanded=True):
        llm_edge_tuples = {tuple(v["edge"]) for v in detail.llm_verdicts}
        baseline_matches = [e for e in detail.correct_edges if e not in llm_edge_tuples]

        if detail.level == 0:
            if baseline_matches:
                st.markdown("**Verified Practice Relationships:**")
                for e in baseline_matches:
                    st.write(f"• `{e[0]}` → `{e[1]}` ({e[2]})")
            elif not detail.llm_verdicts:
                st.write("• No practice relationships matched yet.")
        else:
            if baseline_matches:
                st.markdown(f"• **Benchmark Literature Matches**: **{len(baseline_matches)} of {detail.total_reference_count}** reference relationships correctly connected.")
            elif not detail.llm_verdicts:
                st.write("• **Benchmark Literature Matches**: 0 reference relationships matched yet.")

        if getattr(detail, "nudges", None):
            for nudge in detail.nudges:
                st.info(nudge)

        if detail.llm_verdicts:
            st.markdown("**Verdicts on Novel Relationships:**")
            for v in detail.llm_verdicts:
                badge = "[SUPPORTED]" if v["verdict"] == "supported" else f"[{v['verdict'].upper()}]"
                st.write(f"• `{v['edge'][0]}` → `{v['edge'][1]}` ({v['edge'][2]}): **{badge}** {v.get('reason', '')}")
        elif detail.novel_candidate_edges:
            st.markdown("**Novel Candidate Relationships (Pending Review):**")
            for ne in detail.novel_candidate_edges:
                st.write(f"• `{ne['source_id']}` → `{ne['target_id']}` ({ne['relationship_type']})")

        if detail.injection_hits:
            st.error(
                f"Trap Detected: {len(detail.injection_hits)} connection(s) match misleading AI-prompt injection lures "
                f"(-{detail.injection_penalty:g} pts). Review your sources and discard unverified recommendations."
            )

        if detail.decoy_hits:
            st.warning(
                f"Decoy Detected: {len(detail.decoy_hits)} connection(s) link to decoy papers "
                f"(-{detail.decoy_penalty:g} pts)."
            )


corpus = load_corpus()
vocab = load_vocabulary()
cluster_content_rows = [r for r in _content() if r.get("cluster", "").strip() == team["cluster"]]
content_map = {r["paper_id"]: r for r in cluster_content_rows}

byid = {p["participant_id"]: dict(p) for p in corpus}
demo_l0_spec = load_demo_level0()
for dp in demo_l0_spec.get("papers", []):
    dpid = dp["id"]
    byid[dpid] = {
        "participant_id": dpid,
        "title": dp.get("title", dpid),
        "citation": f"{dpid} · {dp.get('title', '')} ({dp.get('inspired_by', '')})",
        "abstract": dp.get("excerpt", ""),
        "real_world_application": dp.get("real_world_application", ""),
        "authors": ["Research CTF Onboarding Track"],
        "venue": "Introductory Research Overview",
        "year": "2024",
        "challenge_card_path": f"data/participant/cards/{dpid}.pdf",
    }
for pid, r in content_map.items():
    if pid in byid and team["cluster"] != CLUSTER:
        byid[pid]["title"] = r.get("paper_title") or byid[pid]["title"]
        byid[pid]["challenge_card_path"] = r.get("challenge_card_path")
        byid[pid]["citation"] = f"{pid} · {r.get('paper_title', '')}"
        byid[pid]["abstract"] = f"Research excerpt on {r.get('paper_title', '')}."
    elif pid not in byid:
        byid[pid] = {
            "participant_id": pid,
            "title": r.get("paper_title", pid),
            "citation": f"{pid} · {r.get('paper_title', '')}",
            "abstract": f"Research excerpt on {r.get('paper_title', '')}.",
            "challenge_card_path": r.get("challenge_card_path"),
        }

if current is None:
    st.header("Final Event Results")
    st.balloons()
    d = load()
    summary_rows = []
    comp_rows = []
    for lv in team_levels:
        rec = d["submissions"].get(f"{team['team_id']}:{lv['id']}", {})
        gp = rec.get("graph_score", {}).get("points", 0) + rec.get("manual_adjustment", 0)
        fp = rec.get("flag_points", 0)
        is_demo_lv = lv["id"] == 0
        lvl_pts = level_points(lv["id"])
        sim_pct = round(rec.get("graph_score", {}).get("weighted_f1", 0) * 100, 1)
        status_str = "Unscored Demo" if is_demo_lv else ("Correct" if rec.get("flag_correct") else "Incorrect")
        summary_rows.append({
            "Level": f"Level {lv['id']}: {lv['title']}",
            "Submitted Flag": rec.get("submitted_flag", ""),
            "Flag Result": status_str,
            "Flag Points": "-" if is_demo_lv else f"{fp:g} / {lvl_pts['flag']:g}",
            "Graph Points": "-" if is_demo_lv else f"{round(gp, 2):g} / {lvl_pts['graph']:g}",
            "Graph Similarity": "-" if is_demo_lv else f"{sim_pct}%",
            "Level Total": "-" if is_demo_lv else f"{round(fp + gp, 2):g} / {lvl_pts['total']:g}",
            "Edges": rec.get("edge_count", 0),
        })
        if not is_demo_lv:
            comp_rows.append({"fp": fp, "gp": gp, "tot": fp + gp})

    st.dataframe(pd.DataFrame(summary_rows), hide_index=True, use_container_width=True)

    if comp_rows:
        tot_fp = sum(r["fp"] for r in comp_rows)
        tot_gp = sum(r["gp"] for r in comp_rows)
        tot_all = sum(r["tot"] for r in comp_rows)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Flag Points", f"{tot_fp:g} / 8,200 pts")
        c2.metric("Total Graph Points", f"{tot_gp:g} / 12,300 pts")
        c3.metric("Final Event Score", f"{tot_all:g} / 20,500 pts")

    final_sub = d["submissions"].get(f"{team['team_id']}:4")
    if final_sub and final_sub.get("csv"):
        st.subheader("Your Final Cumulative Knowledge Graph")
        try:
            df_final = pd.read_csv(io.StringIO(final_sub["csv"]), dtype=str, keep_default_na=False)
            available_all = released_papers(4, team["cluster"])
            render_graph_diagram(df_final, available=available_all, byid=byid)
        except Exception:
            pass
    st.stop()

# Level 0 includes onboarding Start tab; Levels 1-4 move directly to Papers
just_locked = st.session_state.pop(f"level_just_locked_{team['team_id']}", None)
if just_locked:
    if just_locked.get("is_demo"):
        st.success("Level 0 warm-up complete! You are ready for competition Level 1.")
    else:
        st.success(
            f"Level {just_locked['level']} completed & locked! "
            f"You scored {just_locked['total_points']:g} pts on Level {just_locked['level']} "
            f"(Flag: {just_locked['flag_points']:g} pts, Graph: {just_locked['graph_points']:g} pts · {just_locked['sim_pct']}% similarity)."
        )

tabs_options = ["Start", "Papers", "Knowledge Graph", "Submit"] if current == 0 else ["Papers", "Knowledge Graph", "Submit"]
section = st.radio(
    "Navigate",
    tabs_options,
    index=0,
    horizontal=True,
    label_visibility="collapsed",
    key=f"nav_{team['team_id']}_{current}",
)

available = released_papers(current, team["cluster"])
papers = [byid[pid] for pid in available if pid in byid]
labels = {pid: f"{pid} — {byid[pid]['title']}" for pid in byid}
spec = next(x for x in team_levels if x["id"] == current)
key = f"{team['team_id']}:{current}"

_open = open_level()
if current >= 1 and _open is not None and current > _open:
    st.info(f"Level {current} has not been opened yet. Well done on finishing Level {current - 1} - "
            "the organisers will release the next level shortly. Refresh this page when they announce it.")
    st.stop()


# ==============================================================================
# TAB 1: START (Uniform Challenge Guide & Methodology)
# ==============================================================================
if section == "Start":
    st.subheader("Proof of Thought: Challenge Guide & Methodology")
    st.caption("How to research papers, build cross-disciplinary knowledge graphs, and submit findings.")

    c1, c2, c3 = st.columns(3)
    c1.info("**1. Read & Research**\nInspect papers and download PDF challenge cards on the **Papers** tab.")
    c2.info("**2. Build & Validate**\nConnect cross-paper relationships and validate your CSV on **Knowledge Graph**.")
    c3.info("**3. Submit on Form**\nVerify your flag and submit your cumulative graph and reasoning on **Submit**.")

    with st.expander("Challenge Structure & Scoring Overview", expanded=False):
        st.markdown("""
- **4 Progressive Levels**: Explore published literature spanning computer networks, tree algorithms, and evolutionary biology.
- **Scoring Ratio**: 60% Knowledge Graph similarity + 40% Flag correctness per level.
- **Dynamic Graph Discovery**: Novel verified connections outside the initial reference set are rewarded with discovery bounties.
        """)

    with st.expander(":blue[Relationship Guide: How Papers Connect (Cheat Sheet)]", expanded=False):
        st.markdown(
            """
* **`CITES` (Directional: Citing Paper → Cited Paper)**
  * The arrow MUST go from the paper doing the citing to the paper being cited (`Later Paper → Earlier Paper`).
  * *Example*: `P14 (2004)` surveys and cites `P13 (2004)`, so connect `P14 → P13`.

* **`SHARES_PRINCIPLE` (Symmetric: Shared Core Concept / Math)**
  * Both papers independently rely on the same fundamental mathematical theory or technique (e.g. additive metrics).

* **`ANALOGOUS_PROBLEM` (Symmetric: Cross-Domain Equivalents)**
  * Different scientific fields solving the exact same underlying structural problem (e.g. tree reconstruction in genetics ↔ routing trees on the Internet).

* **`EXTENDS` (Directional: Generalization / Improvement)**
  * Paper A directly builds upon, generalizes, or relaxes assumptions of Paper B (e.g. unicast probes extending multicast probes).

* **`USES_METHOD` (Directional: Subroutine / Tool Application)**
  * Paper A directly imports and applies a method or estimator from Paper B as part of its pipeline.
            """
        )

# ==============================================================================
# TAB 2: PAPERS
# ==============================================================================
elif section == "Papers":
    lvl_label = "Level 0 (Demo)" if current == 0 else f"Level {current}"
    lvl_pts = level_points(current)

    st.subheader(f"{lvl_label}: {spec['title']}")
    if current == 0:
        st.caption("Practice Warm-Up · Unscored")
    else:
        st.caption(f"Maximum Points: **{lvl_pts['total']:g} pts** ({lvl_pts['graph']:g} Graph + {lvl_pts['flag']:g} Flag)")

    st.markdown(f"> **Level Objective**: {spec['question']}")

    st.subheader(f"Papers Released for Level {current}")
    cur_papers = [p for p in papers if p["participant_id"] in spec["paper_ids"]]
    for p in cur_papers:
        with st.expander(f":green[{p['participant_id']} — {p['title']}]", expanded=False):
            authors_str = ", ".join(p.get("authors", [])) if p.get("authors") else ""
            pub_info = f"{p.get('venue', '')} ({p.get('year', '')})".strip()
            meta_parts = []
            if authors_str:
                meta_parts.append(f"**Authors:** {authors_str}")
            if pub_info and pub_info != "()":
                meta_parts.append(f"**Published:** {pub_info}")
            if p.get("domain"):
                meta_parts.append(f"**Domain:** {p['domain']}")
            if meta_parts:
                st.caption(" · ".join(meta_parts))

            c_link, c_dl = st.columns([1, 1])
            url = p.get("open_access_url") or p.get("doi_url")
            if url:
                c_link.markdown(f"[Open original paper link]({url})")
            card_path_val = p.get("challenge_card_path")
            card = None
            if card_path_val:
                candidate = (Path(__file__).parent / card_path_val).resolve()
                cards_root = (Path(__file__).parent / "data" / "participant" / "cards").resolve()
                if candidate.is_relative_to(cards_root) and candidate.exists():
                    card = candidate
            if not card or not card.exists():
                try:
                    card = card_pdf_path(p["participant_id"])
                except Exception:
                    card = None
            if card and card.exists():
                c_dl.download_button(
                    f"Download {p['participant_id']} PDF Card",
                    card.read_bytes(),
                    f"{p['participant_id']}_challenge_card.pdf",
                    "application/pdf",
                    key=f"card_{team['team_id']}_{p['participant_id']}",
                )

    # Previously Released Papers (Earlier Levels) - Only shown if there are earlier competition papers (levels >= 1)
    past_levels_with_papers = []
    for plv in team_levels:
        if 1 <= plv["id"] < current:
            p_list = [byid[pid] for pid in plv["paper_ids"] if pid in byid]
            if p_list:
                past_levels_with_papers.append((plv, p_list))

    if past_levels_with_papers:
        with st.expander(":green[Previously Released Papers (Earlier Levels)]", expanded=False):
            for plv, p_list in past_levels_with_papers:
                st.markdown(f"**Level {plv['id']}: {plv['title']}**")
                for p in p_list:
                    st.caption(f"• **{p['participant_id']}** — {p['title']}")

    # Relationship Guide (Replaces old table, styled blue)
    with st.expander(":blue[Relationship Guide: How Papers Connect (Cheat Sheet)]", expanded=False):
        st.markdown(
            """
**How to choose the correct relationship:**

* **`CITES` (Directional: Citing Paper → Cited Paper)**
  * *Direction*: The arrow MUST go from the paper doing the citing to the paper being cited (`Later Paper → Earlier Paper`).
  * *Example*: `P14 (2004)` surveys and cites `P13 (2004)`, so connect `P14 → P13`. Always check publication years!

* **`SHARES_PRINCIPLE` (Symmetric: Shared Core Concept / Math)**
  * *Definition*: Both papers independently rely on the same fundamental mathematical theory or technique (e.g., additive distance metrics, prefix tree / trie properties).

* **`ANALOGOUS_PROBLEM` (Symmetric: Cross-Domain Equivalents)**
  * *Definition*: Different scientific disciplines solving the exact same underlying structural problem (e.g., evolutionary biologists reconstructing tree lineages in genetics ↔ network engineers reconstructing routing trees on the Internet).

* **`EXTENDS` (Directional: Generalization / Improvement)**
  * *Definition*: Paper A directly builds upon, generalizes, or removes restrictive assumptions of Paper B (e.g. unicast probes extending multicast probes).

* **`USES_METHOD` (Directional: Subroutine / Tool Application)**
  * *Definition*: Paper A directly imports and executes a specific algorithm or estimator introduced by Paper B as part of its pipeline.
            """
        )

    # Hints Ladder (Placed at the very end of the Papers tab, styled yellow)
    ladder = hint_status(team["team_id"], current)
    with st.expander(f":orange[Hints for Level {current}]", expanded=False):
        if not ladder:
            st.caption("No hints configured for this level.")
        for h in ladder:
            cost_str = f"costs {h['cost']:g} pt" if h['cost'] == 1 else f"costs {h['cost']:g} pts"
            label = f"Hint {h['rung']} ({cost_str})"
            if h["revealed"]:
                st.markdown(f"**{label}:** {h['text']}")
            elif h["unlocked"]:
                if st.button(f"Reveal {label}", key=f"hint_{team['team_id']}_{current}_{h['rung']}"):
                    try:
                        reveal_hint(team["team_id"], current, h["rung"])
                    except (ValueError, PermissionError) as e:
                        st.error(str(e))
                    st.rerun()
            else:
                st.caption(f"[Locked] {label} (released by organisers if required).")

# ==============================================================================
# TAB 3: KNOWLEDGE GRAPH
# ==============================================================================
elif section == "Knowledge Graph":
    olddraft = get_draft(team["team_id"], current)
    statekey = f'graph_df_{team["team_id"]}_{current}'
    empty_df = pd.DataFrame(columns=["source_id", "target_id", "relationship_type", "evidence_reference"])
    rels = [r["relationship_type"] for r in vocab["relationship_types"]]

    if statekey not in st.session_state:
        raw_loaded = (
            pd.read_csv(io.StringIO(olddraft), dtype=str, keep_default_na=False) if olddraft.strip() else empty_df.copy()
        )
        for col in empty_df.columns:
            if col not in raw_loaded.columns:
                raw_loaded[col] = ""
        if not raw_loaded.empty:
            valid_loaded, errs_loaded = parse_uploaded_graph_csv(raw_loaded.to_csv(index=False), available, rels)
            cleaned_df = pd.DataFrame(valid_loaded) if valid_loaded else empty_df.copy()
            if errs_loaded:
                try:
                    save_draft(team["team_id"], current, cleaned_df.to_csv(index=False))
                except Exception:
                    pass
            st.session_state[statekey] = cleaned_df
        else:
            st.session_state[statekey] = empty_df.copy()

    df = st.session_state[statekey]

    c_kg_l, c_kg_r = st.columns([3, 1])
    with c_kg_l:
        st.subheader(f"Knowledge Graph Builder · Level {current}")
        st.caption(f"{len(df)} cumulative edges · {len(available)} released papers available to connect.")
    with c_kg_r:
        if not df.empty:
            st.download_button("Download CSV", safe_csv(df), f"{team['team_id']}_level{current}.csv", "text/csv", use_container_width=True)

    # 1. Edge Editor (Dropdowns for source, target, and relationship)
    with st.expander("Add / Remove Graph Edges", expanded=bool(df.empty)):
        st.caption("Tip: Consult the :blue[Relationship Guide] on the Papers tab for connection rules and research nudges.")

        with st.form(f"add_edge_{current}", clear_on_submit=True):
            c1, c2, c3 = st.columns([1.5, 1.5, 1.5])
            src = c1.selectbox("Source paper", available, format_func=lambda x: labels.get(x, x))
            dst = c2.selectbox("Target paper", available, format_func=lambda x: labels.get(x, x))
            rel = c3.selectbox("Relationship type", rels)
            ev = st.text_input("Evidence / Reasoning (optional)", placeholder="Cite key concepts, methods, or reason for this connection...")
            add = st.form_submit_button("Add Edge", type="primary")

        if add:
            if src == dst:
                st.error("A paper cannot be connected to itself.")
            else:
                clean_ev = ev.strip()
                new_row = pd.DataFrame([{"source_id": src, "target_id": dst, "relationship_type": rel, "evidence_reference": clean_ev}])
                clean_base, _ = parse_uploaded_graph_csv(df.to_csv(index=False), available, rels) if not df.empty else ([], [])
                base_df = pd.DataFrame(clean_base) if clean_base else empty_df.copy()
                candidate = pd.concat([base_df, new_row], ignore_index=True).drop_duplicates(
                    subset=["source_id", "target_id", "relationship_type"], keep="first")
                try:
                    save_draft(team["team_id"], current, candidate.to_csv(index=False))
                    st.session_state[statekey] = candidate
                    st.success(f"Added edge: {src} → {dst} ({rel})")
                except (ValueError, PermissionError) as e:
                    st.error(str(e))
                st.rerun()

        if not df.empty:
            st.divider()
            col_del, col_btn, col_clear = st.columns([2.5, 1, 1])
            chosen = col_del.selectbox(
                "Select edge to delete",
                list(df.index),
                format_func=lambda i: f"{df.loc[i, 'source_id']} → {df.loc[i, 'target_id']} ({df.loc[i, 'relationship_type']})",
                label_visibility="collapsed",
            )
            if col_btn.button("Delete edge", use_container_width=True):
                remaining = df.drop(index=chosen).reset_index(drop=True)
                try:
                    save_draft(team["team_id"], current, remaining.to_csv(index=False))
                    st.session_state[statekey] = remaining
                except (ValueError, PermissionError) as e:
                    st.error(str(e))
                st.rerun()
            if col_clear.button("Clear graph", use_container_width=True):
                try:
                    save_draft(team["team_id"], current, empty_df.to_csv(index=False))
                    st.session_state[statekey] = empty_df.copy()
                except (ValueError, PermissionError) as e:
                    st.error(str(e))
                st.rerun()

    # 2. Live Graph Visual (Placed under edge controls)
    st.markdown("#### Live Graph Visual")
    render_graph_diagram(df, available=available, byid=byid)

    # 3. Live Graph Verification Section
    st.markdown("---")
    v_stat = verification_status(team["team_id"], current)
    col_v_info, col_v_btn = st.columns([3, 1.4])
    with col_v_info:
        st.markdown("#### Live Graph Verification")
        if current == 0:
            st.caption(
                "Click below to test your graph against reference literature and novel connections. "
                "Practice Mode: Unlimited live verifications on Level 0."
            )
        else:
            st.caption(
                f"Click below to test your graph against reference literature and novel connections. "
                f"**Allowance: {v_stat['remaining']} of {v_stat['max']} verification checks remaining for Level {current}.**"
            )
    with col_v_btn:
        btn_label = "Verify Graph Live" if current == 0 else f"Verify Graph Live ({v_stat['remaining']}/{v_stat['max']})"
        btn_verify = st.button(
            btn_label,
            key=f"btn_verify_kg_main_{team['team_id']}_{current}",
            type="primary",
            use_container_width=True,
            disabled=bool(current >= 1 and not v_stat["allowed"]),
        )

    if current >= 1 and not v_stat["allowed"]:
        st.warning(f"Verification allowance exhausted ({v_stat['max']}/{v_stat['max']} checks used for Level {current}). Review your graph carefully before final submission.")

    if btn_verify:
        if current >= 1 and not v_stat["allowed"]:
            st.error(f"You have reached the maximum of {v_stat['max']} verification checks for Level {current}.")
        elif df.empty:
            st.warning("Your cumulative graph is currently empty. Add at least one edge in the section above before verifying.")
        else:
            record_verification(team["team_id"], current)
            with st.spinner("Analyzing graph and evaluating connections..."):
                judge = get_live_judge()
                eval_detail = evaluate_submission(
                    team_id=team["team_id"],
                    level=current,
                    flag_answer="",
                    graph_csv=df.to_csv(index=False),
                    cluster=team.get("cluster", CLUSTER),
                    discovery_bounty_pts=0.0,
                    judge=judge,
                    enforce_50pct_floor=False,
                )
                st.session_state[f"live_graph_feedback_{team['team_id']}_{current}"] = eval_detail
                st.rerun()

    # Live Verification Card if evaluated
    live_fb = st.session_state.get(f"live_graph_feedback_{team['team_id']}_{current}")
    if live_fb:
        render_live_verification_card(live_fb)

# ==============================================================================
# TAB 4: SUBMIT
# ==============================================================================
@st.dialog("Confirm Final Level Submission")
def confirm_submission_dialog(team_id: str, level: int, draft: str, is_demo: bool):
    if is_demo or level == 0:
        st.info(
            "**Level 0 Practice Warm-Up**:\n\n"
            "Level 0 is an unscored practice exercise designed to familiarize your team with research cards and knowledge graph validation.\n\n"
            "Confirming will lock your practice answers and advance your team to competition Level 1."
        )
    else:
        st.warning(
            f"**Important Verification Notice**:\n\n"
            f"If you have filled out and submitted the official Google Form for Level {level}, only then move on. "
            f"Once locked, **you will not be allowed to come back and change your answers.**"
        )
        st.link_button(
            f"Open Google Form for Level {level}",
            google_form_url(),
            type="primary",
            use_container_width=True,
        )
    st.divider()
    col_back, col_lock = st.columns([1, 1.5])
    with col_back:
        if st.button("Go Back & Review", use_container_width=True):
            st.session_state.pop(f"show_submit_dialog_{team_id}_{level}", None)
            st.rerun()
    with col_lock:
        lock_label = "Complete Warm-Up — Final Lock" if (is_demo or level == 0) else "Yes, Form Submitted — Final Lock"
        if st.button(lock_label, type="primary", use_container_width=True, key=f"confirm_modal_lock_{team_id}_{level}"):
            st.session_state.pop(f"show_submit_dialog_{team_id}_{level}", None)
            try:
                rec = finalise(team=team_id, level=level, csv_text=draft, explanation="Submitted via official Google Form")
                st.session_state.pop(f'graph_df_{team_id}_{level}', None)
                max_gp = level_points(level)["graph"]
                sim_pct = round(rec["graph_score"].get("weighted_f1", 0) * 100, 1)
                fp = rec.get("flag_points", 0)
                gp = rec.get("graph_score", {}).get("points", 0)
                tot_pts = fp + gp
                st.session_state[f"level_just_locked_{team_id}"] = {
                    "level": level,
                    "flag_points": fp,
                    "graph_points": gp,
                    "sim_pct": sim_pct,
                    "total_points": tot_pts,
                    "is_demo": is_demo,
                }
                st.rerun()
            except (ValueError, PermissionError) as e:
                st.error(str(e))


if section == "Submit":
    d = load()
    rec = d["submissions"].get(key)
    if rec:
        lock_msg = st.session_state.pop(f"lock_msg_{team['team_id']}_{current}", None)
        if lock_msg:
            st.success(lock_msg)
        is_demo = bool(current == 0 or team.get("is_demo"))
        if is_demo:
            st.success("Level 0 warm-up is locked and completed (Unscored Practice).")
        else:
            lvl_pts = level_points(current)
            sim_pct = round(rec.get("graph_score", {}).get("weighted_f1", 0) * 100, 1)
            gp = rec.get("graph_score", {}).get("points", 0) + rec.get("manual_adjustment", 0)
            fp = rec.get("flag_points", 0)
            st.success(f"Level {current} is locked and submitted.")
            c1, c2, c3 = st.columns(3)
            c1.metric("Flag Points", f"{fp:g} / {lvl_pts['flag']:g} pts", "Solved" if rec.get("flag_correct") else "Unsolved")
            c2.metric("Graph Points", f"{gp:g} / {lvl_pts['graph']:g} pts", f"{sim_pct}% similarity")
            c3.metric("Level Total", f"{fp + gp:g} / {lvl_pts['total']:g} pts")
            st.write(f"**Submitted flag:** `{rec.get('submitted_flag', '')}`")
            st.write(f"**Cumulative Graph:** {rec.get('edge_count', 0)} edges ({sim_pct}% similarity to ground truth)")
            if rec.get("manual_adjustment"):
                st.write(f"**Organiser adjustment:** {rec.get('manual_adjustment')} pts ({rec.get('organiser_notes', '')})")
            if rec.get("explanation") and rec.get("explanation") != "Submitted via official Google Form":
                st.write(f"**Explanation:** {rec.get('explanation')}")
            else:
                st.caption("Official responses and reasoning submitted via Google Form.")
        if rec.get("csv"):
            st.subheader("Submitted Graph Diagram")
            df_locked = pd.read_csv(io.StringIO(rec["csv"]), dtype=str, keep_default_na=False)
            render_graph_diagram(df_locked, available=available, byid=byid)
        st.stop()

    is_demo = bool(current == 0 or team.get("is_demo"))
    page_title = "Level 0 Practice Review" if is_demo else f"Level {current} Review & Verification"
    st.subheader(page_title)
    st.caption("Review your flag answer and cumulative graph connections before completing this level.")

    # --- 1. Flag Section ---
    st.markdown("##### 1. Flag Challenge")
    fs = flag_status(team["team_id"], current)
    max_fp = level_points(current)["flag"]

    flag_msg_key = f"flag_feedback_{team['team_id']}_{current}"
    last_feedback = st.session_state.get(flag_msg_key)
    if last_feedback and not fs["correct"]:
        (st.success if last_feedback["correct"] else st.error)(last_feedback["message"])

    if fs["correct"]:
        st.success(f"Flag Solved ({fs['flag_points']:g} / {max_fp:g} pts)")
    elif fs["cooldown_remaining"] > 0:
        st.warning(f"Cooldown active: please wait {fs['cooldown_remaining']} seconds...")
        import time
        time.sleep(fs["cooldown_remaining"])
        st.rerun()
    elif fs["last"] and not last_feedback:
        st.error("Not yet — check the papers again (hints available on the Papers tab).")

    if not fs["correct"]:
        with st.form(f"flag_{current}"):
            col_inp, col_btn = st.columns([3.5, 1.5])
            answer = col_inp.text_input(
                "Flag answer",
                placeholder="Enter your answer...",
                label_visibility="collapsed",
                disabled=bool(fs["cooldown_remaining"] > 0),
            )
            check = col_btn.form_submit_button(
                "Check flag",
                use_container_width=True,
                disabled=bool(fs["cooldown_remaining"] > 0),
            )
        if check:
            if not answer.strip():
                st.warning("Please enter a flag answer before checking.")
            else:
                result = attempt_flag(team["team_id"], current, answer.strip())
                if result["correct"]:
                    st.session_state[flag_msg_key] = {"correct": True, "message": f"Solved! ({result.get('earned_points', max_fp):g} / {max_fp:g} pts)"}
                else:
                    st.session_state[flag_msg_key] = {"correct": False, "message": result.get("message") or "Not yet — check the papers again."}
                st.rerun()

    if fs.get("hint_cost"):
        st.caption(f"Hint deductions on this level: -{fs['hint_cost']:g} pts")

    st.divider()

    # --- 2. Graph Section ---
    st.markdown("##### 2. Knowledge Graph Status")
    draft = get_draft(team["team_id"], current)
    allowed_rels = [r.get("relationship_type") or r.get("name") for r in vocab.get("relationship_types", [])]
    valid_rows, errs = parse_uploaded_graph_csv(draft, available, allowed_rels) if draft.strip() else ([], [])

    c_g_stat, c_g_dl = st.columns([3, 1])
    with c_g_stat:
        if not valid_rows:
            st.warning("Cumulative graph is empty. Add edges in the Knowledge Graph tab.")
        elif errs:
            st.error(f"Graph validation issues ({len(errs)} error(s)):\n" + "\n".join(f"• {e}" for e in errs[:3]))
        else:
            st.success(f"Cumulative Graph: **{len(valid_rows)} edge(s)** ready for submission.")
    with c_g_dl:
        if valid_rows:
            st.download_button("Download CSV", safe_csv(pd.DataFrame(valid_rows)), f"{team['team_id']}_level{current}.csv", "text/csv", use_container_width=True)

    st.markdown("---")

    # --- 3. Completion Section ---
    if is_demo or current == 0:
        st.markdown("##### 3. Complete Warm-Up")
        st.caption("Ready for the competition? Lock your practice answers above to proceed to Level 1.")
    else:
        st.markdown("##### 3. Official Form & Level Lock")
        st.caption("Please fill out and submit all required responses on the official Google Form for this level before locking.")
        st.link_button("Open Official Google Form", google_form_url(), type="primary", use_container_width=True)
        st.markdown("<br>", unsafe_allow_html=True)

    can_submit = bool(draft.strip() and valid_rows and not errs and fs["attempts"] > 0)
    btn_label = f"Lock & Submit Level {current} (Demo)" if is_demo else f"Lock & Submit Level {current}"

    if not can_submit:
        if fs["attempts"] == 0:
            st.caption("Submit at least one flag attempt above to enable level locking.")
        elif not draft.strip() or len(valid_rows) == 0:
            st.caption("Add at least one edge in Knowledge Graph to enable level locking.")
        elif errs:
            st.caption("Fix graph validation issues before level locking.")

    dialog_key = f"show_submit_dialog_{team['team_id']}_{current}"
    if st.session_state.get(dialog_key):
        confirm_submission_dialog(
            team_id=team["team_id"],
            level=current,
            draft=draft,
            is_demo=is_demo,
        )

    if st.button(btn_label, type="primary", disabled=not can_submit):
        in_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        if in_test:
            try:
                rec = finalise(team=team["team_id"], level=current, csv_text=draft, explanation="Submitted via official Google Form")
                st.session_state.pop(f'graph_df_{team["team_id"]}_{current}', None)
                max_gp = level_points(current)["graph"]
                sim_pct = round(rec["graph_score"].get("weighted_f1", 0) * 100, 1)
                fp = rec.get("flag_points", 0)
                gp = rec.get("graph_score", {}).get("points", 0)
                tot_pts = fp + gp
                st.session_state[f"level_just_locked_{team['team_id']}"] = {
                    "level": current,
                    "flag_points": fp,
                    "graph_points": gp,
                    "sim_pct": sim_pct,
                    "total_points": tot_pts,
                    "is_demo": is_demo,
                }
                st.rerun()
            except (ValueError, PermissionError) as e:
                st.error(str(e))
        else:
            st.session_state[dialog_key] = True
            st.rerun()
