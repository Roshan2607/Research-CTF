"""Participant-facing Streamlit interface.

Reads ONLY participant-safe data (``challenge.participant_data``) and talks to
protected data exclusively through ``challenge.submission.ParticipantBackend``,
which returns aggregate, participant-safe results.
"""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from .participant_data import card_pdf_path, load_challenge_info, load_corpus, load_vocabulary
from .submission import ParticipantBackend

EDGE_COLUMNS = ["source_id", "target_id", "relationship_type", "evidence_reference"]

PRIMERS = {
    "What is a research problem?": (
        "The specific question a paper tries to answer. It is narrower than a topic. *Topic:* 'networks'. "
        "*Problem:* 'how can we work out the shape of a network when we can only measure at its edges?' "
        "Look for sentences like *'In this paper we consider the problem of...'*."
    ),
    "What is a methodology?": (
        "How the authors answer the question: the algorithm, model, experiment or proof. Two papers can study "
        "different problems with the same method, or the same problem with different methods. Check the methods "
        "section and any algorithm boxes. The title alone won't tell you."
    ),
    "What is a conceptual relationship?": (
        "A claim that two papers rest on the same underlying idea (a *principle*), even if they use different "
        "words. Example: GPS receivers and earthquake seismologists both locate a source by intersecting distance "
        "estimates. To claim one you must **name the principle** and **show it in both papers**."
    ),
    "What does a knowledge graph represent?": (
        "A set of things (here, papers) joined by typed, directed arrows (relationships). `P07 CITES P02` and "
        "`P07 USES_METHOD P02` are different arrows with different meanings. A knowledge graph is only as good as "
        "the evidence behind each arrow."
    ),
    "How do I cite evidence?": (
        "Give the paper ID plus the place you found it: `P07 p.4, Sec. 2: 'we adopt the estimator of [12]'`, or "
        "`P07 reference [12] = P02`. A quote or page number beats 'it seemed related'."
    ),
    "Why isn't an AI explanation automatically true?": (
        "Language models produce fluent, confident text, including relationships that do not exist. They can also be "
        "steered by text hidden inside the documents they read. Use AI to *find* candidates quickly, then *verify* "
        "each one in the paper. If you can't point to the passage, don't submit the edge."
    ),
}


def _backend() -> ParticipantBackend:
    if "backend" not in st.session_state:
        st.session_state.backend = ParticipantBackend()
    return st.session_state.backend


def _edges_df() -> pd.DataFrame:
    if "edges" not in st.session_state:
        st.session_state.edges = pd.DataFrame(columns=EDGE_COLUMNS)
    return st.session_state.edges


def _csv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    df.fillna("").to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue()


# ------------------------------------------------------------------ sections
def _sidebar(info: dict) -> dict | None:
    st.sidebar.markdown(f"### {info['title']}")
    st.sidebar.caption(info["branding"])
    team = st.session_state.get("team")
    if team:
        st.sidebar.success(f"Signed in as **{team['name']}** ({team['team_id']})")
        if st.sidebar.button("Sign out"):
            st.session_state.pop("team", None)
            st.rerun()
    else:
        code = st.sidebar.text_input("Team code (from the organisers)", type="password")
        if st.sidebar.button("Sign in"):
            t = _backend().login(code)
            if t:
                st.session_state.team = t
                st.rerun()
            else:
                st.sidebar.error("Unknown team code.")
    st.sidebar.divider()
    st.sidebar.markdown(f"**Your starting paper:** `{info['starting_paper']}`")
    st.sidebar.markdown(f"Corpus: {info['corpus_size']} papers, teams of {info['team_size']}")
    return st.session_state.get("team")


def _start_here(info: dict) -> None:
    st.subheader("Your mission")
    st.markdown(
        f"""
You have **{info['corpus_size']} research papers** from biology, computer science, networking and signal processing.
They look unrelated. Some of them aren't.

Your team starts from **{info['starting_paper']}**. Your job:

1. **Read** the papers (start with the abstracts, then the methods sections).
2. **Reconstruct** the relationships between papers as a small knowledge graph, with evidence for each one.
   *(Submission 1: repeatable, scored.)*
3. **Discover** which paper from a *different discipline* shares a deep idea with your starting paper, what that idea
   is, and a **real-world technology** that relies on it every day. *(Submission 2: one attempt only.)*
"""
    )
    st.subheader("Rules")
    for r in info["rules"]:
        st.markdown(f"- {r}")
    st.subheader("Research skills in two minutes")
    for q, a in PRIMERS.items():
        with st.expander(q):
            st.markdown(a)
    st.subheader("Schedule (minutes)")
    st.table(pd.DataFrame(
        [("85-105", "Read papers, start your graph"), ("105-115", "First graph submission"),
         ("115-135", "Correct the graph, explore alternative routes, check evidence"),
         ("135-150", "Find the hidden connection and an application"), ("150-165", "Final one-shot submission"),
         ("165-180", "Solution walkthrough")],
        columns=["Time", "Activity"]))


def _corpus(cards: list[dict]) -> None:
    domains = sorted({c["domain"] for c in cards})
    c1, c2 = st.columns([1, 2])
    dom = c1.multiselect("Filter by domain", domains)
    q = c2.text_input("Search titles and abstracts")
    for c in cards:
        if dom and c["domain"] not in dom:
            continue
        if q and q.lower() not in (c["title"] + " " + c["abstract"]).lower():
            continue
        with st.expander(f"**{c['participant_id']}** · {c['title']} ({c['year']})"):
            st.markdown(f"*{c['citation']}*")
            st.markdown(f"**Domain:** {c['domain']}  \n**Access:** {c['access']}")
            link = c.get("open_access_url") or c["doi_url"]
            st.markdown(f"[Open the paper]({link}) · [DOI]({c['doi_url']})")
            if c.get("first_public_year") and c["first_public_year"] != c["year"]:
                st.caption(f"An earlier version of this work was first made public in {c['first_public_year']}.")
            st.markdown("**Abstract**")
            st.write(c["abstract"])
            st.caption(c["abstract_attribution"])
            st.markdown("**Reading prompts**")
            for i, p in enumerate(c["reading_prompts"], 1):
                st.markdown(f"{i}. {p}")
            try:
                pdf = card_pdf_path(c["participant_id"])
                if pdf.exists():
                    st.download_button("Download challenge card (PDF)", pdf.read_bytes(), file_name=pdf.name,
                                       mime="application/pdf", key=f"dl-{c['participant_id']}")
            except (ValueError, PermissionError):
                pass


def _vocabulary(vocab: dict) -> None:
    st.markdown("Use exactly these relationship types in your submissions.")
    df = pd.DataFrame(vocab["relationship_types"])[["relationship_type", "claim_kind", "direction", "meaning", "example"]]
    st.dataframe(df, hide_index=True, width="stretch")
    for n in vocab["notes"]:
        st.markdown(f"- {n}")


def _graph_builder(ids: list[str], rels: list[str]) -> None:
    st.markdown("Add one row per relationship. Use evidence references like `P07 p.4 Sec. 2` or `P07 ref [12]`.")
    up = st.file_uploader("Load an edge list CSV", type=["csv"], key="edge-upload")
    if up is not None and st.button("Replace table with uploaded file"):
        df = pd.read_csv(up, dtype=str, keep_default_na=False)
        for col in EDGE_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        st.session_state.edges = df[EDGE_COLUMNS]
    edited = st.data_editor(
        _edges_df(), num_rows="dynamic", width="stretch", key="edge-editor",
        column_config={
            "source_id": st.column_config.SelectboxColumn("source_id", options=ids, required=True),
            "target_id": st.column_config.SelectboxColumn("target_id", options=ids, required=True),
            "relationship_type": st.column_config.SelectboxColumn("relationship_type", options=rels, required=True),
            "evidence_reference": st.column_config.TextColumn("evidence_reference"),
        },
    )
    st.session_state.edges = edited
    csv_text = _csv(edited)
    v = _backend().validate(csv_text)
    if v["errors"]:
        st.error("Fix these before submitting:\n\n" + "\n".join(f"- {e}" for e in v["errors"]))
    else:
        st.success(f"{v['n_edges']} valid relationships.")
    for w in v["warnings"]:
        st.warning(w)
    c1, c2 = st.columns(2)
    c1.download_button("Download edge list (CSV)", csv_text, "my_graph.csv", "text/csv")
    if v["ok"] and v["n_edges"]:
        from scoring.kaggle_format import edges_to_kaggle

        rows = [tuple(r) for r in edited[["source_id", "target_id", "relationship_type"]].dropna().itertuples(index=False)]
        kag, _ = edges_to_kaggle([(s.strip().upper(), t.strip().upper(), r.strip().upper()) for s, t, r in rows])
        c2.download_button("Download Kaggle submission", _csv(kag), "kaggle_submission.csv", "text/csv")
    if v["ok"] and v["n_edges"]:
        dot = ["digraph G { rankdir=LR; node [shape=box, style=rounded, fontname=Helvetica];"]
        for r in edited.dropna().itertuples(index=False):
            style = "dir=none" if r.relationship_type in ("SHARES_PRINCIPLE", "ANALOGOUS_PROBLEM") else ""
            dot.append(f'"{r.source_id}" -> "{r.target_id}" [label="{r.relationship_type}" {style}];')
        dot.append("}")
        with st.expander("Preview your graph"):
            st.graphviz_chart("\n".join(dot))


def _submit(team: dict | None) -> None:
    if not team:
        st.info("Sign in with your team code (sidebar) to submit.")
        return
    be = _backend()
    st.markdown(f"Remaining graph submissions: **{be.remaining_submissions(team['team_id'])}**. "
                "You see one aggregate score (weighted F1 on the public half of the answer set), never which edges were right.")
    with st.expander("How is this scored?"):
        st.markdown(
            "- **Recall**: the share of evidence-backed relationships you found.\n"
            "- **Weighted precision**: how much of what you claimed is supported. Unsupported claims cost more "
            "if they come from following an instruction hidden in a document, and less if they come from an "
            "understandable surface-level confusion.\n"
            "- **Weighted F1** combines the two. A wrong relationship *type* counts as wrong.\n"
            "- Some defensible-but-unverified relationships are neither rewarded nor penalised. Organisers may "
            "review new relationships you justify with an evidence reference."
        )
    if st.button("Submit current graph for scoring", type="primary"):
        res = be.submit_graph(team["team_id"], _csv(_edges_df()))
        if res["accepted"]:
            s = res["score"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Weighted F1", f"{s['weighted_f1']:.3f}")
            c2.metric("Weighted precision", f"{s['weighted_precision']:.3f}")
            c3.metric("Recall", f"{s['recall']:.3f}")
        else:
            st.error("\n".join(res["errors"]))
            if res.get("note"):
                st.caption(res["note"])
        for w in res.get("warnings", []):
            st.warning(w)
    hist = be.history(team["team_id"])
    if hist:
        st.markdown("**Your submissions**")
        st.dataframe(pd.DataFrame(hist), hide_index=True, width="stretch")
    lb = be.leaderboard()
    if lb:
        st.markdown("**Leaderboard** (best public score per team)")
        st.dataframe(pd.DataFrame(lb), hide_index=True, width="stretch")


def _hints() -> None:
    hs = _backend().released_hints()
    if not hs:
        st.info("No hints released yet. The organisers release them during the workshop.")
    for h in hs:
        st.markdown(f"**Hint {h['id']}.** {h['text']}")


def _final(team: dict | None, info: dict, ids: list[str]) -> None:
    st.markdown(
        "**One attempt per team.** Once accepted it is locked, and you get no feedback until the deadline. "
        "A product name alone is not enough: explain the idea, show your evidence and state the limits."
    )
    if not team:
        st.info("Sign in with your team code (sidebar) to submit.")
        return
    be = _backend()
    status = be.final_status(team["team_id"])
    if status.get("submitted"):
        st.success(f"Submitted and locked at {status['submitted_at']} (receipt `{status['receipt_id']}`).")
        st.markdown(f"Result: **{status.get('result')}**")
        if status.get("flag"):
            st.code(status["flag"])
        return
    with st.form("final"):
        c1, c2 = st.columns(2)
        base = c1.selectbox("Starting paper", ids, index=ids.index(info["starting_paper"]))
        target = c2.selectbox("Hidden connected paper (from another discipline)", ["-"] + ids)
        principle = st.text_area("The shared principle: explain it in your own words (2-4 sentences)")
        paper_ev = st.text_area("Evidence from the papers (IDs + page/section/quote; include any papers that bridge them)")
        app = st.text_input("Real-world product / technology / application")
        app_ev = st.text_area("Evidence about the application (links to official documentation, technical papers, patents)")
        limits = st.text_area("Limitations: where does the connection break down? Is there any historical link, or just a shared idea?")
        sure = st.checkbox("We understand this is our team's only final submission.")
        go = st.form_submit_button("Submit final answer", type="primary")
    if go:
        if not sure:
            st.error("Tick the confirmation box first.")
            return
        res = be.submit_final(team["team_id"], {
            "base_id": base, "target_id": "" if target == "-" else target, "principle": principle,
            "application": app, "paper_evidence": paper_ev, "application_evidence": app_ev, "limitations": limits})
        if res.get("accepted"):
            st.success(res["message"] + f" Receipt: `{res['receipt_id']}`")
            st.balloons()
        else:
            st.error("\n".join(f"- {e}" for e in res["errors"]))


def render() -> None:
    info = load_challenge_info()
    cards = load_corpus()
    vocab = load_vocabulary()
    ids = [c["participant_id"] for c in cards]
    rels = info["submittable_relationship_types"]
    team = _sidebar(info)
    st.title(info["title"])
    st.caption(f"{info['branding']} · Knowledge Graph CTF · Theme: {info['theme']}")
    tabs = st.tabs(["Start here", "Corpus", "Vocabulary", "Graph builder", "Submit & score", "Hints", "Final discovery"])
    with tabs[0]:
        _start_here(info)
    with tabs[1]:
        _corpus(cards)
    with tabs[2]:
        _vocabulary(vocab)
    with tabs[3]:
        _graph_builder(ids, rels)
    with tabs[4]:
        _submit(team)
    with tabs[5]:
        _hints()
    with tabs[6]:
        _final(team, info, ids)
