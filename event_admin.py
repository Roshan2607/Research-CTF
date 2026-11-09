"""Local-only admin dashboard with periodic live refresh."""
from pathlib import Path
import os, io, html
import pandas as pd
import streamlit as st
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
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from event_core import (
    CLUSTER,
    LEVELS,
    admin_snapshot,
    adjust_submission_score,
    clusters,
    create_admin_session,
    create_cluster_from_template,
    create_team,
    load,
    revoke_admin_session,
    authenticate_admin_session,
)
from challenge.participant_data import load_corpus

st.set_page_config(page_title="Proof of Thought · Admin", page_icon="🔐", layout="wide")
st.title("🔐 Proof of Thought · Admin")
st.caption("Live organiser console and challenge supervisor")

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
        pw = st.text_input("Admin password", type="password")
        ok = st.form_submit_button("Sign in")
    if ok:
        expected = os.environ.get("ORGANISER_PASSWORD", "")
        if len(expected) >= 12 and pw == expected:
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
tabs = st.tabs(["Live dashboard & Leaderboard", "Register Team", "Submissions & Review", "Attempts & Audit Logs"])


@st.fragment(run_every="3s")
def live_dashboard():
    snap = admin_snapshot()
    col_filter, col_demo = st.columns([2, 1])
    cluster_options = ["All clusters"] + clusters()
    selected = col_filter.selectbox("Filter dashboard by cluster", cluster_options, key="admin_dashboard_cluster")
    include_demos = col_demo.checkbox("Include Level 0 Demo teams", value=False, key="admin_include_demos")

    teams = [
        t for t in snap["teams"]
        if (selected == "All clusters" or t["cluster"] == selected)
        and (include_demos or not t.get("is_demo", False))
    ]
    team_ids = {t["team_id"] for t in teams}
    subs = {k: v for k, v in snap["submissions"].items() if v["team_id"] in team_ids}
    finished = sum(len(t["completed_levels"]) == 4 for t in teams)

    a, b, c = st.columns(3)
    a.metric("Active Teams", len(teams))
    b.metric("Completed All 4 Levels", finished)
    c.metric("Locked Level Submissions", len(subs))

    scores = []
    for t in teams:
        team_subs = [v for v in subs.values() if v["team_id"] == t["team_id"]]
        # Per specification: 10 flag points and 15 graph points per level
        flags = sum(v.get("flag_points", (10 if v.get("flag_correct") else 0)) for v in team_subs)
        graph = sum(v.get("graph_score", {}).get("points", 0) for v in team_subs)
        manual = sum(v.get("manual_adjustment", 0.0) for v in team_subs)
        total_graph = round(graph + manual, 2)
        total = round(flags + total_graph, 2)
        scores.append({
            "Team ID": t["team_id"],
            "Team": t["name"] + (" (Demo)" if t.get("is_demo") else ""),
            "Cluster": t["cluster"],
            "Levels Completed": len(team_subs),
            "Flag Points (/40)": flags,
            "Graph Points (/60)": total_graph,
            "Total Score (/100)": total,
        })

    st.subheader("Official Team Leaderboard")
    if scores:
        st.dataframe(pd.DataFrame(scores).sort_values("Total Score (/100)", ascending=False), hide_index=True, use_container_width=True)
    else:
        st.info("No teams yet for this selection.")

    st.subheader("Team Registration & Progress")
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
    st.subheader("Register a Participant or Demo Team")
    available_clusters = clusters()
    if not available_clusters:
        st.error("No clusters configured in data/event_content.csv.")
    else:
        with st.expander("Create a new cluster from a template"):
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
            tid = st.text_input("Team ID (e.g. TEAM01, DEMO01)")
            name = st.text_input("Team Name")
            password = st.text_input("Initial Password (min 8 chars)", type="password")
            selected_cluster = st.selectbox("Assigned Cluster", clusters(), key="team_cluster_select")
            is_demo = st.checkbox("Level 0 Demo Team (excluded from official leaderboard)", value=False)
            ok = st.form_submit_button("Create team", type="primary")

        if ok:
            try:
                created_id = create_team(tid, name, password, selected_cluster, is_demo=is_demo)
                st.success(f"Created {created_id} in {selected_cluster}" + (" (Demo)" if is_demo else ""))
                st.rerun()
            except ValueError as e:
                st.error(str(e))


@st.fragment(run_every="3s")
def submissions_view():
    snap = admin_snapshot()
    teams = {t["team_id"]: t for t in snap["teams"]}
    options = ["All clusters"] + clusters()
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
            c1.metric("Flag Solved", "Yes" if rec.get("flag_correct") else "No")
            c1.caption(f"Flag: {rec.get('submitted_flag') or '(none)'} | Points: {rec.get('flag_points', 0)}/10")
            c2.metric("Cumulative Edges", rec.get("edge_count", 0))
            base_gp = rec.get("graph_score", {}).get("points", 0)
            man_adj = rec.get("manual_adjustment", 0.0)
            c3.metric("Graph Points (/15)", f"{round(base_gp + man_adj, 2)}", delta=f"{man_adj:+} manual" if man_adj else None)

            # --- Participant Explanation Review ---
            st.markdown("#### Participant Explanation & Reasoning")
            explanation = rec.get("explanation", "").strip()
            if explanation:
                st.info(explanation)
            else:
                st.caption("No explanation submitted.")

            # --- Manual Graph Score Adjustment ---
            st.markdown("#### Organiser Score Adjustment")
            with st.form(f"adjust_{sub_key}"):
                col_adj, col_notes = st.columns([1, 2])
                adj_val = col_adj.number_input(
                    "Score Adjustment (+/- pts)",
                    min_value=-15.0,
                    max_value=15.0,
                    value=float(rec.get("manual_adjustment", 0.0)),
                    step=0.5,
                )
                notes_val = col_notes.text_input("Reviewer Notes", value=rec.get("organiser_notes", ""))
                save_adj = st.form_submit_button("Save score adjustment")
            if save_adj:
                adjust_submission_score(rec["team_id"], rec["level"], adj_val, notes_val)
                st.success("Adjustment saved.")
                st.rerun()

            # --- Graph View ---
            st.markdown("#### Submitted Cumulative Graph")
            try:
                df = pd.read_csv(io.StringIO(rec["csv"]), dtype=str, keep_default_na=False)
                df["Source paper"] = df.source_id.map(labels)
                df["Target paper"] = df.target_id.map(labels)
                st.dataframe(df[["Source paper", "relationship_type", "Target paper", "evidence_reference"]], hide_index=True, use_container_width=True)

                dot = [
                    'digraph G { graph [rankdir=LR, bgcolor="#ffffff", pad="0.25"];',
                    'node [shape=box, style="rounded,filled", fillcolor="#EAF2FF", color="#315A8A", fontcolor="#142B45", fontname="Arial", fontsize=10, penwidth=1.5];',
                    'edge [color="#2563EB", fontcolor="#173F7A", fontname="Arial", fontsize=9, penwidth=2, arrowsize=0.8];',
                ]
                for r in df.itertuples():
                    dot.append(f'"{r.source_id}" -> "{r.target_id}" [label="{r.relationship_type}"];')
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


with tabs[3]:
    logs_view()
