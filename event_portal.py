"""Participant portal for the incremental multi-cluster graph challenge."""
from pathlib import Path
import html
import io
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
from scoring.graph_scorer import score_csv

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
    for lv in team_levels:
        rec = d["submissions"].get(f"{team['team_id']}:{lv['id']}", {})
        gp = rec.get("graph_score", {}).get("points", 0) + rec.get("manual_adjustment", 0)
        fp = rec.get("flag_points", 0)
        summary_rows.append({
            "Level": f"Level {lv['id']}: {lv['title']}",
            "Flag Solved": "✅" if rec.get("flag_correct") else "❌",
            "Flag Points (/10)": fp,
            "Graph Points (/15)": round(gp, 2),
            "Total (/25)": round(fp + gp, 2),
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

# ==============================================================================
# TAB 1: START
# ==============================================================================
if section == "Start":
    st.header("How the Challenge Works")
    col1, col2, col3 = st.columns([1.6, 1.0, 1.2])
    col1.metric("Current Level", f"Level {current}", delta=spec["title"], delta_color="off")
    col2.metric("Papers Available", f"{len(available)} of {sum(len(x['paper_ids']) for x in team_levels)}")
    col3.metric("Level Points", "25 pts max", delta="15 Graph + 10 Flag", delta_color="off")

    st.markdown("""
### Guidelines
1. **Cumulative Knowledge Graph**: Build one cumulative graph across all four levels. Each level introduces new papers; you can connect any two distinct papers released so far.
2. **Prior Edges Are Locked**: Relationships submitted in earlier levels remain in your graph and cannot be deleted. You can add new edges and delete uncommitted edges for the current level.
3. **Flag Attempts**:
   - You can test flags freely with instant feedback.
   - The first 5 wrong attempts per level are free; starting from the 6th wrong attempt, each costs 1 flag point.
   - A **30-second cooldown** applies after every wrong attempt.
4. **Finalizing a Level**:
   - Each level requires at least one flag attempt (it does not have to be correct), your cumulative graph, and a brief explanation of your reasoning.
   - Submitting locks the level on the backend and unlocks the next level.
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
    with st.expander("Optional Hints"):
        if spec["hints"]:
            for i, h in enumerate(spec["hints"], 1):
                st.markdown(f"**Hint {i}:** {h}")
        else:
            st.caption("No hints configured for this level.")

# ==============================================================================
# TAB 3: KNOWLEDGE GRAPH
# ==============================================================================
elif section == "Knowledge Graph":
    st.header(f"Knowledge Graph Builder · Level {current}")
    st.caption(f"{len(available)} papers released. You may connect any two different released papers.")

    prior = load()["submissions"].get(f"{team['team_id']}:{current-1}") if current > 1 else None
    locked = (
        pd.read_csv(io.StringIO(prior["csv"]), dtype=str, keep_default_na=False)
        if prior and prior.get("csv", "").strip()
        else pd.DataFrame(columns=["source_id", "target_id", "relationship_type", "evidence_reference"])
    )
    olddraft = get_draft(team["team_id"], current)
    statekey = f'graph_df_{team["team_id"]}_{current}'
    if statekey not in st.session_state:
        st.session_state[statekey] = (
            pd.read_csv(io.StringIO(olddraft), dtype=str, keep_default_na=False)
            if olddraft.strip()
            else locked.copy()
        )
    df = st.session_state[statekey]
    rels = [r["relationship_type"] for r in vocab["relationship_types"]]

    # Edge creation form
    with st.form(f"add_edge_{current}", clear_on_submit=True):
        st.markdown("**Add a Relationship**")
        c1, c2 = st.columns(2)
        src = c1.selectbox("Source paper", available, format_func=lambda x: labels[x])
        dst = c2.selectbox("Target paper", available, format_func=lambda x: labels[x])
        rel = st.selectbox("Relationship type", rels)
        evidence = st.text_input("Evidence reference (page, section or quote)", placeholder="e.g. P02, page 4, Section 3")
        add = st.form_submit_button("Add edge", type="primary")

    if add:
        if src == dst:
            st.error("A paper cannot be connected to itself.")
        elif not evidence.strip():
            st.error("Add an evidence reference.")
        else:
            new_row = pd.DataFrame([{"source_id": src, "target_id": dst, "relationship_type": rel, "evidence_reference": evidence.strip()}])
            st.session_state[statekey] = pd.concat([df, new_row], ignore_index=True)
            save_draft(team["team_id"], current, st.session_state[statekey].to_csv(index=False))
            st.rerun()

    # CSV Upload Feature (including Codex-generated CSV support)
    with st.expander("Import Graph from CSV (e.g. Codex or exported CSV)"):
        uploaded_csv = st.file_uploader("Upload CSV file", type=["csv"], key=f"csv_upload_{team['team_id']}_{current}")
        if uploaded_csv is not None:
            clean_rows, upload_errors = parse_uploaded_graph_csv(uploaded_csv.getvalue(), available, rels)
            if upload_errors:
                st.error("Upload validation failed:\n" + "\n".join(upload_errors[:10]))
            else:
                new_df = pd.DataFrame(clean_rows)
                # Merge with locked edges
                combined = pd.concat([locked, new_df], ignore_index=True).drop_duplicates(
                    subset=["source_id", "target_id", "relationship_type"], keep="first"
                )
                st.session_state[statekey] = combined
                save_draft(team["team_id"], current, combined.to_csv(index=False))
                st.success(f"Successfully imported {len(new_df)} edges! Draft updated.")
                st.rerun()

    df = st.session_state[statekey].copy()
    if not locked.empty:
        locked_keys = set(tuple(x) for x in locked[["source_id", "target_id", "relationship_type", "evidence_reference"]].fillna("").values.tolist())
    else:
        locked_keys = set()

    st.subheader("Cumulative Edge Table")
    display = df.copy()
    display["Source paper"] = display["source_id"].map(labels)
    display["Target paper"] = display["target_id"].map(labels)
    display["Locked"] = display.apply(
        lambda r: tuple(r[["source_id", "target_id", "relationship_type", "evidence_reference"]].fillna("").tolist()) in locked_keys,
        axis=1,
    )
    st.dataframe(display[["Source paper", "relationship_type", "Target paper", "evidence_reference", "Locked"]], hide_index=True, use_container_width=True)

    deletable = [i for i, r in df.iterrows() if tuple(r[["source_id", "target_id", "relationship_type", "evidence_reference"]].fillna("").tolist()) not in locked_keys]
    if deletable:
        chosen = st.selectbox(
            "Select a current-level edge to delete",
            deletable,
            format_func=lambda i: f"{labels.get(df.loc[i, 'source_id'], df.loc[i, 'source_id'])} → {labels.get(df.loc[i, 'target_id'], df.loc[i, 'target_id'])} ({df.loc[i, 'relationship_type']})",
        )
        if st.button("Delete selected edge"):
            st.session_state[statekey] = df.drop(index=chosen).reset_index(drop=True)
            save_draft(team["team_id"], current, st.session_state[statekey].to_csv(index=False))
            st.rerun()
    else:
        st.caption("No deletable current-level edges. Previous-level edges are locked.")

    st.subheader("Live Graph Diagram")
    if not df.empty:
        dot = [
            'digraph G { graph [rankdir=LR, bgcolor="#ffffff", pad="0.25"]; node [shape=box, style="rounded,filled", fillcolor="#EAF2FF", color="#315A8A", fontcolor="#142B45", fontname="Arial", fontsize=10, penwidth=1.5]; edge [color="#2563EB", fontcolor="#173F7A", fontname="Arial", fontsize=9, penwidth=2, arrowsize=0.8];'
        ]
        for pid in available:
            dot.append(f'"{pid}" [label="{pid}\\n{html.escape(byid[pid]["title"][:52])}"];')
        for _, r in df.iterrows():
            typ = r["relationship_type"]
            style = "dir=none" if typ in ("SHARES_PRINCIPLE", "ANALOGOUS_PROBLEM") else "dir=forward"
            dot.append(f'"{r["source_id"]}" -> "{r["target_id"]}" [label="{typ}", {style}];')
        dot.append("}")
        st.graphviz_chart("\n".join(dot), use_container_width=True)
    else:
        st.info("Add the first relationship to see the graph diagram.")

    csv_text = df.to_csv(index=False)
    parsed, _ = score_csv(csv_text, allow_any_pair=True)
    if parsed.errors:
        st.error("Graph validation issues:\n" + "\n".join(parsed.errors))
    else:
        st.success(f"{len(df)} graph edges in current cumulative graph.")

    col_dl, col_save = st.columns([1, 1])
    col_dl.download_button("Download cumulative graph CSV", csv_text, f"{team['team_id']}_level{current}.csv", "text/csv")
    if col_save.button("Save graph draft", type="primary"):
        save_draft(team["team_id"], current, csv_text)
        st.success("Draft saved.")

# ==============================================================================
# TAB 4: SUBMIT
# ==============================================================================
elif section == "Submit":
    st.header(f"Submit Level {current}")
    d = load()
    rec = d["submissions"].get(key)
    if rec:
        st.success(f"Level {current} is locked and submitted.")
        st.write(f"**Submitted flag:** {rec.get('submitted_flag')} ({rec.get('flag_points', 0)}/10 pts)")
        st.write(f"**Graph score:** {rec.get('graph_score', {}).get('points', 0)}/15 pts ({rec.get('edge_count', 0)} edges)")
        if rec.get("manual_adjustment"):
            st.write(f"**Organiser adjustment:** {rec.get('manual_adjustment')} pts ({rec.get('organiser_notes', '')})")
        st.write(f"**Explanation:** {rec.get('explanation')}")
        st.stop()

    # --- 1. Flag Section ---
    st.subheader(f"1. Flag Check")
    st.write(spec["question"])
    fs = flag_status(team["team_id"], current)

    if fs["cooldown_remaining"] > 0:
        st.warning(f"⏳ Cooldown active: wait {fs['cooldown_remaining']}s")
    elif fs["correct"]:
        st.success(f"✅ Correct ({fs['flag_points']}/10 pts)")
    elif fs["last"]:
        st.error(f"❌ Incorrect")

    with st.form(f"flag_{current}"):
        col_inp, col_btn = st.columns([4, 1])
        answer = col_inp.text_input("Flag answer", placeholder="Type your answer here", label_visibility="collapsed")
        check = col_btn.form_submit_button("Check flag", use_container_width=True, disabled=bool(fs["cooldown_remaining"] > 0))

    if check:
        if answer.strip():
            result = attempt_flag(team["team_id"], current, answer)
            if result["correct"]:
                st.success(result["message"])
            else:
                st.error(result["message"])
            st.rerun()

    st.caption(f"Attempts: {fs['attempts']}")

    st.divider()

    # --- 2. Graph & Explanation ---
    st.subheader("2. Cumulative Graph & Explanation")
    draft = get_draft(team["team_id"], current)

    if team["cluster"] == CLUSTER:
        parsed, result = score_csv(draft, allow_any_pair=True)
    else:
        allowed_rels = [r["name"] for r in vocab.get("relationship_types", [])]
        valid_rows, errs = parse_uploaded_graph_csv(draft, available, allowed_rels)
        parsed = type("ParsedSubmissionCompat", (), {"errors": errs, "edges": valid_rows, "evidence": {}})()
        result = None

    if not draft.strip() or len(parsed.edges) == 0:
        st.warning("Cumulative graph is empty. Add at least one edge in the Knowledge Graph tab before submitting.")
    elif parsed.errors:
        st.error("Graph validation issues:\n" + "\n".join(parsed.errors))
    else:
        with st.expander(f"Review Cumulative Graph ({len(parsed.edges)} edges)", expanded=False):
            df_preview = pd.read_csv(io.StringIO(draft), dtype=str, keep_default_na=False)
            df_preview["Source paper"] = df_preview.source_id.map(labels).fillna(df_preview.source_id)
            df_preview["Target paper"] = df_preview.target_id.map(labels).fillna(df_preview.target_id)
            st.dataframe(df_preview[["Source paper", "relationship_type", "Target paper", "evidence_reference"]], hide_index=True, use_container_width=True)

    explanation_key = f"expl_input_{team['team_id']}_{current}"
    explanation = st.text_area(
        "Explanation & Reasoning",
        value=st.session_state.get(explanation_key, ""),
        placeholder="Briefly describe your key cross-paper connections, reasoning, and evidence...",
        key=explanation_key,
        height=100,
    )

    st.divider()

    # --- 3. Final Submit Button ---
    can_submit = bool(draft.strip() and len(parsed.edges) > 0 and not parsed.errors and fs["attempts"] > 0)
    if not can_submit:
        if fs["attempts"] == 0:
            st.caption("ℹ️ Submit at least one flag attempt above to enable level locking.")

    if st.button(f"Lock & Submit Level {current}", type="primary", disabled=not can_submit):
        if not explanation.strip():
            st.error("Please provide an explanation before submitting.")
            st.stop()

        if result:
            metrics = result.organiser_view()["public"]
            graph_points = round(metrics["weighted_f1"] * 15.0, 2)
            score_dict = {
                "weighted_f1": metrics["weighted_f1"],
                "weighted_precision": metrics["weighted_precision"],
                "recall": metrics["recall"],
                "points": graph_points,
                "edges": len(parsed.edges),
            }
        else:
            score_dict = {
                "weighted_f1": 0.0,
                "weighted_precision": 0.0,
                "recall": 0.0,
                "points": 0.0,
                "edges": len(parsed.edges),
            }

        try:
            finalise(
                team=team["team_id"],
                level=current,
                csv_text=draft,
                flag_correct=fs["correct"],
                graph_score=score_dict,
                submitted_flag=fs["last"]["answer"] if fs["last"] else "",
                explanation=explanation.strip(),
            )
            st.session_state.pop(f'graph_df_{team["team_id"]}_{current}', None)
            st.session_state.pop(explanation_key, None)
            st.success(f"Level {current} successfully locked! Next level unlocked.")
            st.rerun()
        except (ValueError, PermissionError) as e:
            st.error(str(e))
