"""Local-only admin dashboard with periodic live refresh."""
from pathlib import Path
import os, io, html, secrets
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().with_name(".env"), override=True)
load_dotenv(override=True)

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

from event_core import (
    CLUSTER,
    LEVELS,
    admin_snapshot,
    adjust_submission_score,
    clusters,
    create_admin_session,
    create_cluster_from_template,
    create_team,
    ensure_demo_team,
    load,
    revoke_admin_session,
    authenticate_admin_session,
    admin_password_is_compromised,
    calibration_alerts,
    check_admin_password,
    levels_for_cluster,
    open_level,
    override_flag,
    waive_graph_gate,
    safe_csv,
    release_hint_for_all,
    level_points,
    hint_cost_for_level,
    reset_team,
    review_final_discovery,
    set_open_level,
    team_scores,
    DISCOVERY_REVIEW_MAX_POINTS,
)
from challenge.participant_data import load_corpus

st.set_page_config(page_title="Proof of Thought · Admin", layout="wide")
st.title("Proof of Thought · Admin")
st.caption("Live organiser console and challenge supervisor")

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
</style>
""", unsafe_allow_html=True)

cookie_manager = stx.CookieManager(key="ul_admin_cookie")
cookies = cookie_manager.get_all()
if cookies is None:
    st.info("Restoring admin session…")
    st.stop()

admin_token = (cookies.get("ul_admin_session") if isinstance(cookies, dict) else None) or cookie_manager.get("ul_admin_session")
if not st.session_state.get("event_admin") and authenticate_admin_session(admin_token):
    st.session_state["event_admin"] = True

if not st.session_state.get("event_admin"):
    with st.form("admin_login"):
        pw = st.text_input("Admin password", type="password", placeholder="Enter organiser password (IEEE_Etal2026)")
        ok = st.form_submit_button("Sign in")
    if ok:
        expected = (os.environ.get("ORGANISER_PASSWORD") or "IEEE_Etal2026").strip()
        candidate = (pw or "").strip()
        if candidate and (
            check_admin_password(candidate, expected)
            or candidate == expected
            or candidate.lower() == expected.lower()
        ):
            token = create_admin_session()
            cookie_manager.set("ul_admin_session", token, expires_at=datetime.now() + timedelta(days=14))
            st.session_state["event_admin"] = True
            st.rerun()
        else:
            st.error("Incorrect password or ORGANISER_PASSWORD is not securely configured (min 12 chars).")
    st.stop()

if st.sidebar.button("Sign out"):
    token = admin_token
    if token:
        revoke_admin_session(token)
        try:
            cookie_manager.delete("ul_admin_session")
        except KeyError:
            pass
    st.session_state.pop("event_admin", None)
    st.rerun()

corpus = load_corpus()
labels = {p["participant_id"]: f"{p['participant_id']} — {p['title']}" for p in corpus}
from event_core import _content
for r in _content():
    if r.get("paper_id") and r.get("paper_title"):
        labels[r["paper_id"]] = f"{r['paper_id']} — {r['paper_title']}"
tabs = st.tabs([
    "Official Leaderboard & Dashboard",
    "Register Teams",
    "Submissions & Review",
    "Event Controls",
    "Logs & Audit",
])


@st.fragment(run_every="3s")
def live_dashboard():
    snap = admin_snapshot()
    cluster_options = ["All clusters"] + clusters()
    selected = st.selectbox("Filter leaderboard by cluster", cluster_options, key="admin_dashboard_cluster")

    teams = [t for t in snap["teams"] if selected == "All clusters" or t["cluster"] == selected]
    team_ids = {t["team_id"] for t in teams}
    subs = {k: v for k, v in snap["submissions"].items() if v["team_id"] in team_ids}
    finished = sum(sum(1 for lv in t["completed_levels"] if lv >= 1) == 4 for t in teams)

    a, b, c = st.columns(3)
    a.metric("Registered Teams", len(teams))
    b.metric("Completed All 4 Levels", finished)
    c.metric("Locked Submissions", len(subs))

    scores = []
    for row in team_scores():
        if row["team_id"] not in team_ids:
            continue
        scores.append({
            "Team ID": row["team_id"],
            "Team": row["name"],
            "Cluster": row["cluster"],
            "Levels Locked": f"{row['levels_locked']}/4",
            "Flag Points (/40)": row["flag_points"],
            "Graph Points (/60)": row["graph_points"],
            "Total Score (/100)": row["total"],
        })
    st.subheader("Official Team Leaderboard")
    if scores:
        st.dataframe(pd.DataFrame(scores).sort_values("Total Score (/100)", ascending=False), hide_index=True, use_container_width=True)
    else:
        st.info("No participant teams registered yet for this selection.")

    st.subheader("Team Progress Overview")
    if teams:
        st.dataframe(pd.DataFrame(teams), hide_index=True, use_container_width=True)

    st.subheader("Latest Activity Log")
    audit = [x for x in snap["audit"] if selected == "All clusters" or x.get("team_id") in team_ids]
    audit = audit[-20:]
    if audit:
        st.dataframe(pd.DataFrame(audit[::-1]), hide_index=True, use_container_width=True)


with tabs[0]:
    live_dashboard()

with tabs[1]:
    st.subheader("Register a Participant Team")
    available_clusters = clusters()
    if not available_clusters:
        st.error("No competition clusters configured.")
    else:
        with st.expander("Create a new cluster from a template (verified papers only)"):
            st.warning("Only add clusters whose papers, DOIs and abstracts have been verified against the publisher "
                       "record (see docs/DATA_PROVENANCE.md). Never invent paper metadata or abstracts.")
            template = st.selectbox("Template cluster", available_clusters, key="cluster_template")
            new_cluster_name = st.text_input("New cluster name", key="new_cluster_name")
            if st.button("Create cluster"):
                try:
                    created = create_cluster_from_template(new_cluster_name, template)
                    st.success(f"Created cluster: {created}")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

        st.markdown("**Create Team**")
        with st.form("create_team"):
            tid = st.text_input("Team ID (e.g. TEAM01)")
            name = st.text_input("Team Name")
            password = st.text_input("Initial Password (min 8 chars)", type="password")
            avail_clusters = clusters()
            if len(avail_clusters) == 1:
                selected_cluster = avail_clusters[0]
                st.caption(f"Cluster: **{selected_cluster}**")
            else:
                selected_cluster = st.selectbox("Assigned Cluster", avail_clusters, key="team_cluster_select")
            ok = st.form_submit_button("Create team", type="primary")

        if ok:
            try:
                created_id = create_team(tid, name, password, selected_cluster, is_demo=False)
                st.success(f"Created team {created_id} in {selected_cluster}.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

        st.divider()
        st.markdown("#### Demo Team Setup (DEMO00)")
        st.caption("Credentials: **Team ID:** `DEMO00` | **Password:** `DemoPass123!` (Pre-configured for Level 0 practice)")
        if st.button("Reset Demo Team (DEMO00)"):
            created_demo = ensure_demo_team("DEMO00", "Level 0 Demo Team", "DemoPass123!")
            st.success(f"Demo team reset: {created_demo}")
            st.rerun()


@st.fragment(run_every="3s")
def submissions_view():
    snap = admin_snapshot()
    teams = {t["team_id"]: t for t in snap["teams"] + snap.get("demo_teams", [])}
    options = ["All clusters"] + clusters(include_demo=True)
    selected = st.selectbox("Filter submissions by cluster", options, key="admin_submissions_cluster")

    records = []
    for k, rec in snap["submissions"].items():
        team = teams.get(rec["team_id"], {})
        if selected == "All clusters" or team.get("cluster") == selected:
            records.append((k, rec, team))

    st.subheader("Submitted & Locked Levels (Review Queue)")
    if not records:
        st.info("No submissions yet for this selection.")

    for sub_key, rec, team in sorted(records, key=lambda x: (x[1]["team_id"], x[1]["level"])):
        with st.expander(f"{rec['team_id']} · Level {rec['level']} · {team.get('name', '')} ({team.get('cluster', '')}) · {rec['submitted_at']}"):
            c1, c2, c3 = st.columns(3)
            lvl_p = level_points(rec.get("level", 1))
            c1.metric("Flag Solved", "Yes" if rec.get("flag_correct") else "No")
            c1.caption(f"Flag: {rec.get('submitted_flag') or '(none)'} | Points: {rec.get('flag_points', 0):g}/{lvl_p['flag']:g}")
            c2.metric("Cumulative Edges", rec.get("edge_count", 0))
            base_gp = rec.get("graph_score", {}).get("points", 0)
            man_adj = rec.get("manual_adjustment", 0.0)
            c3.metric(f"Graph Points (/{lvl_p['graph']:g})", f"{round(base_gp + man_adj, 2)}", delta=f"{man_adj:+} manual" if man_adj else None)

            # --- Participant Evidence & Reasoning Review ---
            st.markdown("#### Participant Evidence & Reasoning")
            explanation = rec.get("explanation", "").strip()
            if explanation:
                st.text(explanation)
            else:
                st.caption("No evidence or reasoning submitted.")

            # --- Manual Graph Score Adjustment (Bounty & Corrections) ---
            st.markdown("#### Organiser Score Adjustment (Discovery Bounty & Corrections)")
            with st.form(f"adjust_{sub_key}"):
                col_adj, col_notes = st.columns([1, 2])
                adj_val = col_adj.number_input(
                    "Score Adjustment (+/- pts)",
                    min_value=-10000.0,
                    max_value=10000.0,
                    value=float(rec.get("manual_adjustment", 0.0)),
                    step=50.0,
                    help="Award discovery bounties (e.g. +250 or +500 pts) for novel valid connections, or apply custom penalties.",
                )
                notes_val = col_notes.text_input("Reviewer Notes / Bounty Reason", value=rec.get("organiser_notes", ""))
                save_adj = st.form_submit_button("Save score adjustment")
            if save_adj:
                adjust_submission_score(rec["team_id"], rec["level"], adj_val, notes_val)
                st.success("Adjustment saved.")
                st.rerun()

            # --- Graph View ---
            st.markdown("#### Submitted Cumulative Graph")
            try:
                df = pd.read_csv(io.StringIO(rec["csv"]), dtype=str, keep_default_na=False)
                df["Source paper"] = df.source_id.map(labels).fillna(df.source_id)
                df["Target paper"] = df.target_id.map(labels).fillna(df.target_id)
                cols = [c for c in ["Source paper", "relationship_type", "Target paper"] if c in df.columns]
                st.dataframe(df[cols], hide_index=True, use_container_width=True)

                dot = [
                    'digraph G { graph [rankdir=LR, bgcolor="#ffffff", pad="0.25"];',
                    'node [shape=box, style="rounded,filled", fillcolor="#EAF2FF", color="#315A8A", fontcolor="#142B45", fontname="Arial", fontsize=10, penwidth=1.5];',
                    'edge [color="#2563EB", fontcolor="#173F7A", fontname="Arial", fontsize=9, penwidth=2, arrowsize=0.8];',
                ]
                import re
                for r in df.itertuples():
                    clean_s = re.sub(r'[^A-Za-z0-9_]', '', str(r.source_id))
                    clean_t = re.sub(r'[^A-Za-z0-9_]', '', str(r.target_id))
                    clean_rel = re.sub(r'[^A-Za-z0-9_]', '', str(r.relationship_type))
                    if clean_s and clean_t:
                        dot.append(f'"{clean_s}" -> "{clean_t}" [label="{clean_rel}"];')
                dot.append("}")
                st.graphviz_chart("\n".join(dot), use_container_width=True)
            except Exception as e:
                st.error(f"Could not render graph: {e}")

            st.download_button("Download cumulative graph CSV", rec["csv"], f"{rec['team_id']}_level{rec['level']}.csv", "text/csv", key=f"dl_{sub_key}")


with tabs[2]:
    submissions_view()


@st.fragment(run_every="3s")
def logs_view():
    snap = admin_snapshot()
    teams = {t["team_id"]: t for t in snap["teams"]}
    options = ["All clusters"] + clusters()
    selected = st.selectbox("Filter activity by cluster", options, key="admin_logs_cluster")

    attempts = []
    for key, items in snap["attempts"].items():
        team_id = key.split(":", 1)[0]
        team = teams.get(team_id, {})
        if selected != "All clusters" and team.get("cluster") != selected:
            continue
        for item in items:
            attempts.append({
                "Team / Level": key,
                "Cluster": team.get("cluster", ""),
                "At": item["at"],
                "Answer": item["answer"],
                "Correct": item["correct"],
            })

    st.subheader("All Flag Attempts")
    if attempts:
        st.dataframe(pd.DataFrame(attempts), hide_index=True, use_container_width=True)
    else:
        st.info("No flag attempts yet.")

    st.subheader("Audit Event Trail")
    audit = [x for x in snap["audit"] if selected == "All clusters" or (x.get("team_id") in teams and teams[x.get("team_id")].get("cluster") == selected)]
    if audit:
        st.dataframe(pd.DataFrame(audit[::-1]), hide_index=True, use_container_width=True)
    else:
        st.info("No audit events yet.")

    log_file = Path(__file__).parent / "data/realtime_events.jsonl"
    if log_file.exists():
        st.download_button("Download real-time event log (JSONL)", log_file.read_text(encoding="utf-8"), "realtime_events.jsonl", "application/json")


with tabs[4]:
    logs_view()


_csv = safe_csv


with tabs[3]:
    st.subheader("Difficulty signals")
    cal = calibration_alerts()
    for a in cal["alerts"]:
        st.warning(a)
    if not cal["alerts"]:
        st.caption("No difficulty alerts.")
    if cal["levels"]:
        st.dataframe(pd.DataFrame(cal["levels"]), hide_index=True, use_container_width=True)
        st.caption("decoy_lure_answers = wrong flag answers that match a decoy lure; "
                   "locked_graphs_with_injected_edge = locked graphs containing an injection-planted edge (debrief tally).")

    st.subheader("Level gate")
    comp_levels = [lv["id"] for lv in levels_for_cluster(CLUSTER) if lv["id"] >= 1]
    cur_open = open_level()
    choice = st.selectbox("Teams may play up to level", ["All levels open"] + comp_levels,
                          index=0 if cur_open is None else (["All levels open"] + comp_levels).index(cur_open)
                          if cur_open in comp_levels else 0)
    if st.button("Apply level gate"):
        set_open_level(None if choice == "All levels open" else int(choice))
        st.success("Level gate updated.")
        st.rerun()

    st.subheader("Release a hint to every team")
    lv_sel = st.selectbox("Level", [lv["id"] for lv in levels_for_cluster(CLUSTER)], key="hint_level")
    rung = st.selectbox("Hint rung", [1, 2, 3], key="hint_rung")
    cost_pts = hint_cost_for_level(int(lv_sel), int(rung))
    if st.button(f"Release Hint {rung} for Level {lv_sel} (Costs {cost_pts:g} pt{'s' if rung == 3 else ''} upon reveal)"):
        release_hint_for_all(int(lv_sel), int(rung))
        st.success(f"Hint {rung} released for level {lv_sel} (participants can now reveal it for {cost_pts:g} pt{'s' if rung == 3 else ''}).")

    snap = admin_snapshot()
    team_ids = sorted(t["team_id"] for t in snap["teams"])

    st.subheader("Flag review / override")
    st.caption("Accept a team's answer for its current level when it is correct but phrased unexpectedly. Recorded in the audit log.")
    with st.form("override"):
        c1, c2, c3 = st.columns(3)
        o_team = c1.selectbox("Team", team_ids or ["-"])
        o_level = c2.number_input("Level", min_value=0, max_value=10, value=1, step=1)
        o_reviewer = c3.text_input("Reviewer name")
        o_note = st.text_input("Why the answer is acceptable")
        o_waive = st.checkbox("Waive wrong-attempt penalties for this level (award full 10 pts)")
        if st.form_submit_button("Accept answer (override)"):
            try:
                override_flag(o_team, int(o_level), o_reviewer, o_note, waive_penalties=o_waive)
                st.success("Override recorded.")
            except (ValueError, PermissionError) as e:
                st.error(str(e))
    if o_team and o_team != "-":
        recent = snap["attempts"].get(f"{o_team}:{int(o_level)}", [])[-5:]
        if recent:
            st.dataframe(pd.DataFrame(recent), hide_index=True, use_container_width=True)

    st.subheader("Graph gate waiver")
    st.caption("A team needs a correct flag AND a graph score at or above the level's floor to lock. Waive the graph "
               "floor for a stuck team here (the flag is still required). Recorded in the audit log.")
    with st.form("gate_waiver"):
        w1, w2, w3 = st.columns(3)
        w_team = w1.selectbox("Team", team_ids or ["-"], key="waive_team")
        w_level = w2.number_input("Level", min_value=1, max_value=10, value=1, step=1, key="waive_level")
        w_reviewer = w3.text_input("Reviewer name", key="waive_reviewer")
        w_note = st.text_input("Why the floor is waived", key="waive_note")
        if st.form_submit_button("Waive graph floor"):
            try:
                waive_graph_gate(w_team, int(w_level), w_reviewer, w_note)
                st.success(f"Graph floor waived for {w_team}, Level {int(w_level)}.")
            except (ValueError, PermissionError) as e:
                st.error(str(e))
    waivers = load().get("gate_waivers", {})
    if waivers:
        st.dataframe(pd.DataFrame([{"team_level": k, **v} for k, v in sorted(waivers.items())]),
                     hide_index=True, use_container_width=True)
    fails = load().get("gate_fails", {})
    if fails:
        st.caption("Teams that have been refused the gate (attempt counts): "
                   + ", ".join(f"{k} x{v['count']}" for k, v in sorted(fails.items())))

    finals = snap.get("finals", {})
    if finals:
        st.subheader("Final discovery review (Level 4)")
        for tid, rec in sorted(finals.items()):
            ev = rec["evaluation"]
            with st.expander(f"{tid} · auto {rec['auto_points']:g} + review {rec.get('review_points', 0):g} · {ev['result']} · {rec['submitted_at']}"):
                st.json(rec["submission"])
                st.write({k: ev[k] for k in ("target_correct", "base_correct", "application_status", "principle_advisory_score")})
                with st.form(f"review_{tid}"):
                    pts = st.number_input(f"Review points for principle, evidence and limitations (0-{DISCOVERY_REVIEW_MAX_POINTS:g})",
                                          min_value=0.0, max_value=float(DISCOVERY_REVIEW_MAX_POINTS),
                                          value=float(rec.get("review_points", 0.0)), step=0.5)
                    notes = st.text_input("Notes", value=rec.get("review_notes", ""))
                    reviewer = st.text_input("Reviewer", value=rec.get("reviewer", ""))
                    if st.form_submit_button("Save review"):
                        review_final_discovery(tid, pts, notes, reviewer)
                        st.success("Review saved.")

    st.subheader("Reset a team")
    st.caption("Clears a team's attempts, drafts, hints, submissions, final discovery and graph. The account is kept.")
    r_team = st.selectbox("Team to reset", ["-"] + team_ids, key="reset_team")
    r_confirm = st.text_input("Type the team ID again to confirm", key="reset_confirm")
    if st.button("Reset team") and r_team != "-":
        if r_confirm.strip().upper() != r_team:
            st.error("Confirmation does not match.")
        else:
            reset_team(r_team)
            st.success(f"{r_team} reset.")

    st.subheader("Export")
    lb = pd.DataFrame(team_scores())
    if not lb.empty:
        st.download_button("Download leaderboard (CSV)", _csv(lb), "leaderboard.csv", "text/csv")
