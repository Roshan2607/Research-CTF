"""Participant portal for the incremental multi-cluster graph challenge."""
from pathlib import Path
import html
import io
from datetime import datetime, timedelta

import extra_streamlit_components as stx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from challenge.participant_data import card_pdf_path, load_corpus, load_vocabulary
from event_core import (
    CLUSTER,
    LEVELS,
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

st.set_page_config(page_title="Uncharted Literature · Participant", page_icon="🧭", layout="wide")
st.title("🧭 Uncharted Literature")

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
papers = [p for p in corpus if p["participant_id"] in available]
byid = {p["participant_id"]: p for p in corpus}
labels = {p["participant_id"]: f"{p['participant_id']} — {p['title']}" for p in corpus}
spec = next(x for x in team_levels if x["id"] == current)
key = f"{team['team_id']}:{current}"

# ==============================================================================
# TAB 1: START
# ==============================================================================
if section == "Start":
    st.header("How the Challenge Works")
    col1, col2, col3 = st.columns(3)
    col1.metric("Current Level", f"Level {current}: {spec['title']}")
    col2.metric("Papers Available", f"{len(available)} of {sum(len(x['paper_ids']) for x in team_levels)}")
    col3.metric("Level Points", "15 Graph + 10 Flag = 25 pts")

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
        st.dataframe(pd.DataFrame(vocab["relationship_types"]), hide_index=True, use_container_width=True)

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
                card = card_pdf_path(p["participant_id"])
                if card.exists():
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
                    st.session_state[statekey] = combined
                    save_draft(team["team_id"], current, combined.to_csv(index=False))
                    st.success(f"Successfully imported {len(new_df)} edges! Draft updated.")
                    st.rerun()
            except Exception as e:
                st.error(f"Could not parse uploaded CSV: {e}")

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
    st.header(f"Submit & Lock Level {current}")
    d = load()
    rec = d["submissions"].get(key)
    if rec:
        st.success("This level has already been submitted and locked.")
        st.write(f"**Submitted at:** {rec.get('submitted_at')}")
        st.write(f"**Submitted flag:** {rec.get('submitted_flag')}")
        st.write(f"**Flag score:** {rec.get('flag_points', 0)} / 10 pts")
        st.write(f"**Graph score:** {rec.get('graph_score', {}).get('points', 0)} / 15 pts")
        if rec.get("manual_adjustment"):
            st.write(f"**Organiser adjustment:** {rec.get('manual_adjustment')} pts ({rec.get('organiser_notes', '')})")
        st.write(f"**Explanation:** {rec.get('explanation')}")
        st.stop()

    # --- 1. Flag Section ---
    st.subheader(f"1. Flag Check · Level {current}")
    st.write(spec["question"])
    fs = flag_status(team["team_id"], current)

    if fs["cooldown_remaining"] > 0:
        st.warning(f"⏳ Cooldown active: please wait {fs['cooldown_remaining']}s before checking another flag.")
    elif fs["correct"]:
        st.success(f"✅ Correct flag solved! ({fs['flag_points']}/10 flag points earned)")
    elif fs["last"]:
        st.error(f"❌ Most recent flag was incorrect. (Total attempts: {fs['attempts']}; {fs['wrong_attempts']} wrong)")

    with st.form(f"flag_{current}"):
        answer = st.text_input("Enter flag answer", placeholder="Type your answer here")
        check = st.form_submit_button("Check flag", disabled=bool(fs["cooldown_remaining"] > 0))

    if check:
        result = attempt_flag(team["team_id"], current, answer)
        if result["correct"]:
            st.success(result["message"])
        else:
            st.error(result["message"])
        st.rerun()

    st.caption(
        f"Attempts logged: {fs['attempts']} (First 5 wrong attempts are free; 6th onwards costs 1 pt. 30s cooldown applies after wrong attempts)."
    )

    st.divider()

    # --- 2. Graph Verification ---
    st.subheader("2. Cumulative Graph Verification")
    draft = get_draft(team["team_id"], current)
    if not draft.strip():
        st.warning("Your cumulative graph is empty. Add at least one edge in the Knowledge Graph tab before submitting.")
        st.stop()

    parsed, result = score_csv(draft, allow_any_pair=True)
    if parsed.errors:
        st.error("Please fix these graph validation errors in the Knowledge Graph tab before submitting:\n" + "\n".join(parsed.errors))
        st.stop()

    st.write(f"**Edges to submit:** {len(parsed.edges)}")
    df_preview = pd.read_csv(io.StringIO(draft), dtype=str, keep_default_na=False)
    df_preview["Source paper"] = df_preview.source_id.map(labels)
    df_preview["Target paper"] = df_preview.target_id.map(labels)
    st.dataframe(df_preview[["Source paper", "relationship_type", "Target paper", "evidence_reference"]], hide_index=True, use_container_width=True)

    st.divider()

    # --- 3. Explanation Form ---
    st.subheader("3. Graph Explanation & Reasoning")
    st.caption("Explain the core connections discovered, your reasoning, and key paper evidence (required for organiser review).")
    explanation_key = f"expl_input_{team['team_id']}_{current}"
    explanation = st.text_area(
        "Explanation text",
        value=st.session_state.get(explanation_key, ""),
        placeholder="Describe how the papers connect across domains, the evidence supporting these edges, and any limitations observed...",
        key=explanation_key,
    )

    st.divider()

    # --- 4. Final Confirmation & Lock ---
    st.subheader("4. Review & Finalize")
    if fs["attempts"] == 0:
        st.warning("⚠️ You must submit at least one flag attempt in Section 1 before you can finalize this level.")
        st.stop()

    flag_submitted = fs["last"]["answer"] if fs["last"] else ""
    st.write(f"**Flag status:** {'✅ Solved' if fs['correct'] else '❌ Not solved'} (Points: {fs['flag_points']}/10)")
    st.write(f"**Cumulative graph edges:** {len(parsed.edges)}")

    confirm = st.checkbox("We have reviewed our cumulative graph, flag, and explanation and wish to lock this level.", key=f"confirm_{team['team_id']}_{current}")

    if st.button("Submit and unlock next level", type="primary", disabled=not confirm):
        if not explanation.strip():
            st.error("Please provide an explanation in Section 3 before submitting.")
            st.stop()

        metrics = result.organiser_view()["public"]
        # Per specification: 15 graph points per level based on weighted F1
        graph_points = round(metrics["weighted_f1"] * 15.0, 2)
        score_dict = {
            "weighted_f1": metrics["weighted_f1"],
            "weighted_precision": metrics["weighted_precision"],
            "recall": metrics["recall"],
            "points": graph_points,
            "edges": len(parsed.edges),
        }

        try:
            finalise(
                team=team["team_id"],
                level=current,
                csv_text=draft,
                flag_correct=fs["correct"],
                graph_score=score_dict,
                submitted_flag=flag_submitted,
                explanation=explanation.strip(),
            )
            st.session_state.pop(f'graph_df_{team["team_id"]}_{current}', None)
            st.session_state.pop(explanation_key, None)
            st.success(f"Level {current} successfully locked! Next level unlocked.")
            st.rerun()
        except (ValueError, PermissionError) as e:
            st.error(str(e))
