"""Participant portal for the incremental multi-cluster graph challenge."""
from pathlib import Path
import html
import io
import re
from datetime import datetime, timedelta

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
from event_core import (
    CLUSTER,
    LEVELS,
    _content,
    attempt_flag,
    final_discovery_status,
    final_results_visible,
    hint_status,
    open_level,
    reveal_hint,
    submit_final_discovery,
    authenticate,
    authenticate_session,
    create_session,
    finalise,
    flag_status,
    get_draft,
    levels_for_cluster,
    load,
    released_papers,
    revoke_session,
    save_draft,
    team_progress,
    parse_uploaded_graph_csv,
)

st.set_page_config(page_title="Proof of Thought · Participant", page_icon="🧭", layout="wide")
st.title("🧭 Proof of Thought")

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

cookie_manager = stx.CookieManager(key="ul_participant_cookie")
cookies = cookie_manager.get_all()
if cookies is None:
    st.info("Restoring participant session…")
    st.stop()


def login():
    st.subheader("Participant login")
    with st.form("login"):
        tid = st.text_input("Team ID")
        pw = st.text_input("Password", type="password")
        ok = st.form_submit_button("Sign in", type="primary")
    if ok:
        user = authenticate(tid, pw)
        if user:
            token = create_session(user["team_id"])
            cookie_manager.set("ul_team_session", token, expires_at=datetime.now() + timedelta(days=14))
            st.session_state["event_team"] = user
            st.rerun()
        else:
            st.error("Invalid team ID or password.")


team = st.session_state.get("event_team")
if not team:
    token = (cookies.get("ul_team_session") if isinstance(cookies, dict) else None) or cookie_manager.get("ul_team_session")
    if token:
        team = authenticate_session(token)
        st.session_state["event_team"] = team if team else None

if not team:
    login()
    st.stop()

st.caption(f"Cluster: {team['cluster']}")
team_levels = levels_for_cluster(team["cluster"])
completed, current = team_progress(team["team_id"])

with st.sidebar:
    st.success(f"{team['name']} · {team['team_id']}")
    if team.get("is_demo"):
        st.info("Demo Team (Level 0)")
    st.markdown("### Level progress")
    for lv in team_levels:
        icon = "✅" if lv["id"] in completed else ("🟡" if lv["id"] == current else "🔒")
        st.write(f"{icon} Level {lv['id']}: {lv['title']}")
    if st.button("Sign out"):
        token_to_revoke = (cookies.get("ul_team_session") if isinstance(cookies, dict) else None) or cookie_manager.get("ul_team_session")
        revoke_session(token_to_revoke)
        try:
            cookie_manager.delete("ul_team_session")
        except KeyError:
            pass
        st.session_state.pop("event_team", None)
        st.rerun()

if current is None:
    st.success(f"All {len(team_levels)} levels completed!")
    # Show summary of all submitted levels
    d = load()
    summary_rows = []
    reveal_final = final_results_visible()
    for lv in team_levels:
        rec = d["submissions"].get(f"{team['team_id']}:{lv['id']}", {})
        gp = rec.get("graph_score", {}).get("points", 0) + rec.get("manual_adjustment", 0)
        fp = rec.get("flag_points", 0)
        hidden = rec.get("final_discovery") and not reveal_final
        summary_rows.append({
            "Level": f"Level {lv['id']}: {lv['title']}",
            "Flag Solved": "hidden until deadline" if hidden else ("✅" if rec.get("flag_correct") else "❌"),
            "Flag Points (/10)": "hidden" if hidden else fp,
            "Graph Points (/15)": round(gp, 2),
            "Total (/25)": "hidden" if hidden else round(fp + gp, 2),
            "Edges": rec.get("edge_count", 0),
        })
    st.subheader("Your Final Event Results")
    st.dataframe(pd.DataFrame(summary_rows), hide_index=True, use_container_width=True)
    st.stop()

# Exactly Four Tabs as per specification: Start, Papers, Knowledge Graph, Submit
section = st.radio(
    "Navigate",
    ["Start", "Papers", "Knowledge Graph", "Submit"],
    horizontal=True,
    label_visibility="collapsed",
    key=f"nav_{team['team_id']}_{current}",
)

corpus = load_corpus()
vocab = load_vocabulary()
available = released_papers(current, team["cluster"])
cluster_content_rows = [r for r in _content() if r.get("cluster", "").strip() == team["cluster"]]
content_map = {r["paper_id"]: r for r in cluster_content_rows}

byid = {p["participant_id"]: dict(p) for p in corpus}
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

papers = [byid[pid] for pid in available if pid in byid]
labels = {pid: f"{pid} — {byid[pid]['title']}" for pid in byid}
spec = next(x for x in team_levels if x["id"] == current)
key = f"{team['team_id']}:{current}"

_open = open_level()
if current >= 1 and _open is not None and current > _open:
    st.info(f"Level {current} has not been opened yet. Well done on finishing Level {current - 1} - "
            "the organisers will release the next level shortly. Refresh this page when they announce it.")
    st.stop()


def render_graph_diagram(df: pd.DataFrame, available: list | None = None, byid: dict | None = None) -> None:
    """Render a clean Graphviz diagram from an edge dataframe."""
    if df is None or df.empty:
        st.info("No edges in the cumulative graph to display.")
        return

    byid = byid or {}
    node_set = list(available) if available else []
    for pid in sorted(set(df["source_id"].dropna().unique()) | set(df["target_id"].dropna().unique())):
        if pid not in node_set:
            node_set.append(pid)

    dot = [
        'digraph G { graph [rankdir=LR, bgcolor="#ffffff", pad="0.25"]; '
        'node [shape=box, style="rounded,filled", fillcolor="#EAF2FF", color="#315A8A", fontcolor="#142B45", fontname="Arial", fontsize=10, penwidth=1.5]; '
        'edge [color="#2563EB", fontcolor="#173F7A", fontname="Arial", fontsize=9, penwidth=2, arrowsize=0.8];'
    ]

    for pid in node_set:
        clean_pid = re.sub(r'[^A-Za-z0-9_]', '', str(pid).strip().upper())
        title = byid.get(pid, {}).get("title", "") if pid in byid else ""
        clean_title = re.sub(r'["\\\r\n]', ' ', str(title[:50])).strip()
        lbl = f"{clean_pid}\\n{clean_title}" if clean_title else clean_pid
        dot.append(f'"{clean_pid}" [label="{lbl}"];')

    for _, r in df.iterrows():
        clean_s = re.sub(r'[^A-Za-z0-9_]', '', str(r.get("source_id", "")).strip().upper())
        clean_t = re.sub(r'[^A-Za-z0-9_]', '', str(r.get("target_id", "")).strip().upper())
        clean_rel = re.sub(r'[^A-Za-z0-9_]', '', str(r.get("relationship_type", "")).strip())
        style = "dir=none" if clean_rel in ("SHARES_PRINCIPLE", "ANALOGOUS_PROBLEM") else "dir=forward"
        if clean_s and clean_t:
            dot.append(f'"{clean_s}" -> "{clean_t}" [label=" {clean_rel} ", {style}];')

    dot.append("}")
    st.graphviz_chart("\n".join(dot), use_container_width=True)

# ==============================================================================
# TAB 1: START
# ==============================================================================
if section == "Start":
    st.header("How the Challenge Works")
    col1, col2, col3 = st.columns([1.6, 1.0, 1.2])
    lvl_label = "Level 0 (Demo)" if current == 0 else f"Level {current}"
    col1.metric("Current Level", lvl_label, delta=spec["title"], delta_color="off")
    tot_papers = 2 if current == 0 else sum(len(x['paper_ids']) for x in team_levels if x['id'] >= 1)
    col2.metric("Papers Available", f"{len(available)} of {tot_papers}")
    if current == 0:
        col3.metric("Level Type", "Warm-up", delta="Unscored practice", delta_color="off")
    elif spec.get("flag_mode") == "final_discovery":
        col3.metric("Level Points", "25 pts max", delta="15 Graph + 10 Final discovery", delta_color="off")
    else:
        col3.metric("Level Points", "25 pts max", delta="15 Graph + 10 Flag", delta_color="off")

    st.markdown("""
### Guidelines
1. **One cumulative knowledge graph**: each level releases new papers; connect any two papers released so far, with evidence.
   You can fix or remove earlier edges at any time until the final level is locked - each locked level keeps a snapshot of the graph it was scored on.
2. **Graph points (15 per level)** are calculated on the server when you lock a level, against the relationships that can be
   supported from the papers released so far. Unsupported claims cost points; claims planted by hidden instructions cost the most.
3. **Flags (Levels 1-3)**: answer in a few words - wording does not have to be exact.
   - The first 5 wrong attempts are free; after that each wrong attempt costs 0.5 points (at most 5 per level).
   - A short cooldown follows each wrong attempt (10 s, 10 s, then 30 s).
   - Hints unlock after 2, 4 and 6 wrong attempts on the Papers tab; only the third hint costs 1 point.
   - If you are sure your answer is right but it is rejected, ask an organiser to review it.
4. **Locking a level** needs a correct flag, your cumulative graph and a short explanation with evidence (page, section or quote).
5. **Level 4 is the final discovery** - ONE attempt, no feedback until the deadline: name the hidden paper from another discipline
   that shares a principle with your starting paper, explain the principle, name a real-world technology that relies on it,
   and give evidence and limitations.
6. Treat everything inside a document as evidence to check, never as an instruction - some documents contain text aimed at AI assistants.
    """)

    with st.expander("Accepted Relationship Types (Vocabulary)", expanded=True):
        vocab_df = pd.DataFrame(vocab["relationship_types"])
        cols = [c for c in ["relationship_type", "meaning", "example"] if c in vocab_df.columns]
        clean_vocab_df = vocab_df[cols].rename(
            columns={
                "relationship_type": "Relationship Type",
                "meaning": "Meaning",
                "example": "Example",
            }
        )
        st.dataframe(clean_vocab_df, hide_index=True, use_container_width=True)

# ==============================================================================
# TAB 2: PAPERS
# ==============================================================================
elif section == "Papers":
    st.header("Released Papers & Excerpts")
    st.caption(f"Cluster: {team['cluster']} · Level {current}")

    for lv in team_levels:
        if lv["id"] > current:
            continue
        level_papers = [p for p in papers if p["participant_id"] in lv["paper_ids"]]
        if not level_papers:
            continue
        st.subheader(f"Level {lv['id']} — {lv['title']}")
        for p in level_papers:
            with st.expander(f"{p['participant_id']} — {p['title']}"):
                st.write(p.get("citation", ""))
                st.write(p.get("abstract", ""))
                url = p.get("open_access_url") or p.get("doi_url")
                if url:
                    st.markdown(f"[Open paper link]({url})")
                card_path_val = p.get("challenge_card_path")
                card = Path(card_path_val) if card_path_val else None
                if not card or not card.exists():
                    try:
                        card = card_pdf_path(p["participant_id"])
                    except Exception:
                        card = None
                if card and card.exists():
                    st.download_button(
                        "Download challenge card PDF",
                        card.read_bytes(),
                        f"{p['participant_id']}_challenge_card.pdf",
                        "application/pdf",
                        key=f"card_{team['team_id']}_{p['participant_id']}",
                    )

    st.divider()
    st.subheader("Level Guidance & Instructions")
    st.markdown(f"**Level {current} Objective:** {spec['question']}")

    with st.expander("General Reading Prompts (Guide for any paper)", expanded=True):
        st.markdown("""
1. **Problem**: What problem does the paper try to solve? Summarize in one sentence.
2. **Hidden vs Observed**: What is hidden or unknown, and what is directly measured?
3. **Methods**: What method or abstraction do the authors introduce?
4. **Evidence**: What evidence is provided (proofs, simulations, empirical data)?
5. **Assumptions & Limitations**: What assumptions constrain this work?
6. **Cross-Domain Analogies**: Which other papers share this principle or mathematical structure?
        """)

    st.markdown("#### Hints")
    ladder = hint_status(team["team_id"], current)
    if not ladder:
        st.caption("No hints configured for this level.")
    for h in ladder:
        label = f"Hint {h['rung']}" + (f" (costs {h['cost']:g} point)" if h["cost"] else "")
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
            when = (f"after {h['unlock_after_wrong']} wrong flag attempts or when the organisers release it"
                    if spec.get("flag_mode") != "final_discovery" else "when the organisers release it")
            st.caption(f"🔒 {label} unlocks {when}.")

# ==============================================================================
# TAB 3: KNOWLEDGE GRAPH
# ==============================================================================
elif section == "Knowledge Graph":
    st.header(f"Knowledge Graph Builder · Level {current}")
    st.caption(f"{len(available)} papers released. You may connect any two different released papers. "
               "Earlier edges stay editable until the final level is locked.")

    olddraft = get_draft(team["team_id"], current)
    statekey = f'graph_df_{team["team_id"]}_{current}'
    empty_df = pd.DataFrame(columns=["source_id", "target_id", "relationship_type", "evidence_reference"])
    if statekey not in st.session_state:
        st.session_state[statekey] = (
            pd.read_csv(io.StringIO(olddraft), dtype=str, keep_default_na=False) if olddraft.strip() else empty_df.copy()
        )
    df = st.session_state[statekey]
    for col in empty_df.columns:
        if col not in df.columns:
            df[col] = ""
    rels = [r["relationship_type"] for r in vocab["relationship_types"]]

    with st.form(f"add_edge_{current}", clear_on_submit=True):
        st.markdown("**Add a Relationship**")
        c1, c2, c3 = st.columns([1.5, 1.5, 1.5])
        src = c1.selectbox("Source paper", available, format_func=lambda x: labels.get(x, x))
        dst = c2.selectbox("Target paper", available, format_func=lambda x: labels.get(x, x))
        rel = c3.selectbox("Relationship type", rels)
        evidence = st.text_input("Evidence (page, section or reference number)", placeholder="e.g. P12 p.5, Sec. 2")
        add = st.form_submit_button("Add edge", type="primary")

    if add:
        if src == dst:
            st.error("A paper cannot be connected to itself.")
        else:
            new_row = pd.DataFrame([{"source_id": src, "target_id": dst, "relationship_type": rel, "evidence_reference": evidence.strip()}])
            candidate = pd.concat([df, new_row], ignore_index=True).drop_duplicates(
                subset=["source_id", "target_id", "relationship_type"], keep="first")
            try:
                save_draft(team["team_id"], current, candidate.to_csv(index=False))
                st.session_state[statekey] = candidate
            except (ValueError, PermissionError) as e:
                st.error(str(e))
            st.rerun()

    with st.expander("Import Graph from CSV (e.g. Codex or exported CSV)"):
        uploaded_csv = st.file_uploader("Upload CSV file", type=["csv"], key=f"csv_upload_{team['team_id']}_{current}")
        if uploaded_csv is not None:
            clean_rows, upload_errors = parse_uploaded_graph_csv(uploaded_csv.getvalue(), available, rels)
            if upload_errors:
                st.error("Upload validation failed:\n" + "\n".join(upload_errors[:10]))
            elif st.button("Replace my graph with this file"):
                new_df = pd.DataFrame(clean_rows)
                try:
                    save_draft(team["team_id"], current, new_df.to_csv(index=False))
                    st.session_state[statekey] = new_df
                    st.success(f"Imported {len(new_df)} edges. Draft updated.")
                except (ValueError, PermissionError) as e:
                    st.error(str(e))
                st.rerun()

    df = st.session_state[statekey].copy()
    st.subheader("Cumulative Edge Table")
    display = df.copy()
    display["Source paper"] = display["source_id"].map(labels).fillna(display["source_id"])
    display["Target paper"] = display["target_id"].map(labels).fillna(display["target_id"])
    st.dataframe(display[["Source paper", "relationship_type", "Target paper", "evidence_reference"]],
                 hide_index=True, use_container_width=True)

    if not df.empty:
        chosen = st.selectbox(
            "Select an edge to delete",
            list(df.index),
            format_func=lambda i: f"{labels.get(df.loc[i, 'source_id'], df.loc[i, 'source_id'])} → "
                                  f"{labels.get(df.loc[i, 'target_id'], df.loc[i, 'target_id'])} ({df.loc[i, 'relationship_type']})",
        )
        if st.button("Delete selected edge"):
            remaining = df.drop(index=chosen).reset_index(drop=True)
            try:
                save_draft(team["team_id"], current, remaining.to_csv(index=False))
                st.session_state[statekey] = remaining
            except (ValueError, PermissionError) as e:
                st.error(str(e))
            st.rerun()

    st.subheader("Live Graph Diagram")
    if not df.empty:
        render_graph_diagram(df, available=available, byid=byid)
    else:
        st.info("Add the first relationship to see the graph diagram.")

    csv_text = df.to_csv(index=False)
    _, errs = parse_uploaded_graph_csv(csv_text, available, rels) if not df.empty else ([], [])
    if errs:
        st.error("Graph validation issues:\n" + "\n".join(errs))
    else:
        st.success(f"{len(df)} edges in your cumulative graph.")
    st.download_button("Download cumulative graph CSV", csv_text, f"{team['team_id']}_level{current}.csv", "text/csv")

# ==============================================================================
# TAB 4: SUBMIT
# ==============================================================================
elif section == "Submit":
    st.header(f"Submit Level {current}")
    d = load()
    rec = d["submissions"].get(key)
    if rec:
        st.success(f"Level {current} is locked and submitted.")
        st.write(f"**Submitted flag:** `{rec.get('submitted_flag', '')}` ({rec.get('flag_points', 0)}/10 pts)")
        st.write(f"**Graph score:** {rec.get('graph_score', {}).get('points', 0)}/15 pts ({rec.get('edge_count', 0)} edges)")
        if rec.get("manual_adjustment"):
            st.write(f"**Organiser adjustment:** {rec.get('manual_adjustment')} pts ({rec.get('organiser_notes', '')})")
        st.write(f"**Explanation:** {rec.get('explanation')}")
        if rec.get("csv"):
            st.subheader("Submitted Graph Diagram")
            df_locked = pd.read_csv(io.StringIO(rec["csv"]), dtype=str, keep_default_na=False)
            render_graph_diagram(df_locked, available=available, byid=byid)
        st.stop()

    # --- 1. Flag Section ---
    st.subheader("1. Flag Check")
    st.write(spec["question"])
    fs = flag_status(team["team_id"], current)
    if fs["correct"]:
        st.success(f"✅ Solved ({fs['flag_points']:g}/10 pts)")
    elif fs["cooldown_remaining"] > 0:
        st.warning(f"⏳ Cooldown active: wait {fs['cooldown_remaining']}s")
    elif fs["last"]:
        st.error("❌ Not yet - check the papers again (hints unlock on the Papers tab).")
    if not fs["correct"]:
        with st.form(f"flag_{current}"):
            col_inp, col_btn = st.columns([4, 1])
            answer = col_inp.text_input("Flag answer", placeholder="A few words are enough", label_visibility="collapsed")
            check = col_btn.form_submit_button("Check flag", use_container_width=True, disabled=bool(fs["cooldown_remaining"] > 0))
        if check and answer.strip():
            result = attempt_flag(team["team_id"], current, answer)
            (st.success if result["correct"] else st.error)(result["message"])
            st.rerun()
    st.caption(f"Attempts: {fs['attempts']} · wrong: {fs['wrong_attempts']} · penalty: {fs['penalty_points']:g}"
               + (f" · hint cost: {fs['hint_cost']:g}" if fs.get("hint_cost") else ""))

    st.divider()

    # --- 2. Graph & Evidence ---
    st.subheader("2. Cumulative Graph & Evidence")
    draft = get_draft(team["team_id"], current)
    allowed_rels = [r.get("relationship_type") or r.get("name") for r in vocab.get("relationship_types", [])]
    valid_rows, errs = parse_uploaded_graph_csv(draft, available, allowed_rels) if draft.strip() else ([], [])
    if not valid_rows:
        st.warning("Your cumulative graph is empty. Add at least one edge in the Knowledge Graph tab before submitting.")
    elif errs:
        st.error("Graph validation issues:\n" + "\n".join(errs))
    else:
        with st.expander(f"Review Cumulative Graph ({len(valid_rows)} edges)", expanded=False):
            df_preview = pd.DataFrame(valid_rows)
            df_preview["Source paper"] = df_preview.source_id.map(labels).fillna(df_preview.source_id)
            df_preview["Target paper"] = df_preview.target_id.map(labels).fillna(df_preview.target_id)
            st.dataframe(df_preview[["Source paper", "relationship_type", "Target paper", "evidence_reference"]],
                         hide_index=True, use_container_width=True)
        st.caption("Graph points are calculated on the server when you lock this level.")

    explanation_key = f"expl_input_{team['team_id']}_{current}"
    explanation = st.text_area(
        "Evidence & Reasoning",
        value=st.session_state.get(explanation_key, ""),
        placeholder="Cite the key evidence (page, section, quotes) and explain your cross-paper reasoning...",
        key=explanation_key,
        height=120,
    )

    st.divider()

    # --- 3. Final Confirmation Review ---
    st.subheader(f"3. Final Confirmation · Level {current}")
    st.caption("Review your final flag attempt and cumulative graph preview before locking your submission.")

    final_flag_val = fs["last"]["answer"] if fs["last"] else ""
    col_flag_rev, col_graph_rev = st.columns(2)
    with col_flag_rev:
        st.markdown(f"**Submitted Flag Attempt:** `{final_flag_val or 'No flag attempted'}`")
        if fs["correct"]:
            st.success(f"Flag Status: ✅ Correct ({fs['flag_points']:g}/10 pts)")
        elif fs["last"]:
            st.error("Flag Status: ❌ Incorrect (0/10 pts — advancing permitted)")
        else:
            st.warning("Flag Status: ⚠️ No flag attempt submitted yet")

    with col_graph_rev:
        st.markdown(f"**Cumulative Graph Edges:** {len(valid_rows)}")
        if errs:
            st.error(f"Graph Status: ❌ {len(errs)} validation error(s)")
        elif len(valid_rows) > 0:
            st.success(f"Graph Status: ✅ Valid ({len(valid_rows)} edges)")
        else:
            st.warning("Graph Status: ⚠️ Cumulative graph is empty")

    if draft.strip() and len(valid_rows) > 0 and not errs:
        st.markdown("**Graph Diagram Preview:**")
        df_preview = pd.DataFrame(valid_rows)
        render_graph_diagram(df_preview, available=available, byid=byid)

    st.markdown("---")
    can_submit = bool(draft.strip() and valid_rows and not errs and fs["attempts"] > 0)
    if not can_submit:
        if fs["attempts"] == 0:
            st.caption("ℹ️ Submit at least one flag attempt in Section 1 above to enable level locking.")
        elif not draft.strip() or len(valid_rows) == 0:
            st.caption("ℹ️ Add at least one edge in Knowledge Graph to enable level locking.")
        elif errs:
            st.caption("ℹ️ Fix graph validation issues before level locking.")

    if st.button(f"Lock & Submit Level {current}", type="primary", disabled=not can_submit):
        if not explanation.strip():
            st.error("Please provide an explanation before submitting.")
            st.stop()
        try:
            rec = finalise(team=team["team_id"], level=current, csv_text=draft, explanation=explanation.strip())
            st.session_state.pop(f'graph_df_{team["team_id"]}_{current}', None)
            st.session_state.pop(explanation_key, None)
            st.success(f"Level {current} locked. Graph points: {rec['graph_score']['points']:g}/15.")
            st.rerun()
        except (ValueError, PermissionError) as e:
            st.error(str(e))
