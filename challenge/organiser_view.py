"""Organiser console (protected). Run on localhost only:

    streamlit run organiser_app.py --server.address 127.0.0.1 --server.port 8502

Access requires ORGANISER_PASSWORD from the environment (.env). This module may
read every data layer; it is never imported by the participant app.
"""
from __future__ import annotations

import hmac
import io
import json
import os
import subprocess
import sys

import pandas as pd
import streamlit as st

from graph.builder import build_graph, load_master_records, paper_projection
from graph.validation import errors, validate_records

from . import paths
from .hints import all_hints
from .submission_store import SubmissionStore

ROLE_COLOURS = {"base": "#2b8a3e", "target": "#c92a2a", "intermediate": "#e67700", "decoy": "#868e96", "alt": "#1971c2"}


def _auth() -> bool:
    expected = os.environ.get("ORGANISER_PASSWORD", "")
    if not expected or expected == "change-me":
        st.error("ORGANISER_PASSWORD is not configured. Set it in .env (see .env.example) and restart.")
        return False
    if st.session_state.get("organiser_ok"):
        return True
    pw = st.text_input("Organiser password", type="password")
    if st.button("Unlock"):
        if hmac.compare_digest(pw.encode(), expected.encode()):
            st.session_state.organiser_ok = True
            st.rerun()
        st.error("Wrong password.")
    return False


def _csv(df: pd.DataFrame) -> str:
    b = io.StringIO()
    df.to_csv(b, index=False, lineterminator="\n")
    return b.getvalue()


def _roles() -> dict[str, str]:
    canon = paths.read_json(paths.CANONICAL_PATH)
    alts = paths.read_json(paths.ALTERNATIVE_PATHS)["paths"]
    decoys = paths.read_json(paths.DECOYS)["decoys"]
    roles = {}
    for a in alts:
        for n in a["path"]:
            roles[n] = "alt"
    for n in canon["path"][1:-1]:
        roles[n] = "intermediate"
    roles[canon["base"]["internal_id"]] = "base"
    roles[canon["target"]["internal_id"]] = "target"
    for d in decoys:
        roles[d["internal_id"]] = "decoy"
    return roles


def _paper_dot(g, roles, highlight: list[str] | None = None) -> str:
    pg = paper_projection(g)
    hl = set(zip(highlight or [], (highlight or [])[1:]))
    hl |= {(b, a) for a, b in hl}
    lines = ["graph G { layout=neato; overlap=false; splines=true; node [shape=box, style=\"rounded,filled\", fontname=Helvetica, fontsize=10];"]
    for n in pg.nodes:
        d = g.nodes[n]
        col = ROLE_COLOURS.get(roles.get(n), "#dee2e6")
        font = "white" if roles.get(n) in ("base", "target", "intermediate", "decoy", "alt") else "black"
        lines.append(f'"{n}" [label="{d["participant_id"]}\\n{d["authors"][0].split()[-1]} {d["year"]}", fillcolor="{col}", fontcolor="{font}"];')
    seen = set()
    for a, b, data in pg.edges(data=True):
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        rels = sorted({d["rel"] for d in pg.get_edge_data(a, b).values()})
        w = "3" if (a, b) in hl else "1"
        col = "#c92a2a" if (a, b) in hl else "#495057"
        lines.append(f'"{a}" -- "{b}" [label="{"/".join(r[:4] for r in rels)}", fontsize=7, penwidth={w}, color="{col}"];')
    lines.append("}")
    return "\n".join(lines)


def render() -> None:
    st.title("Uncharted Literature · Organiser console")
    st.caption("OpenAI × IEEE CS × Research Et Al · ORGANISER ONLY - do not project this screen during the challenge")
    if not _auth():
        return
    records = load_master_records()
    g = build_graph(records)
    store = SubmissionStore()
    roles = _roles()
    tabs = st.tabs(["Build & validate", "Master graph", "Canonical & alternatives", "Decoys", "Injections",
                    "Evidence", "Pipeline", "Teams", "Leaderboard & submissions", "Review queue",
                    "Final flags", "Hints", "AI-injection demo"])

    with tabs[0]:
        issues = validate_records(records)
        errs = errors(issues)
        st.metric("Graph", f"{len(records['nodes'])} nodes / {len(records['edges'])} edges")
        (st.error if errs else st.success)(f"{len(errs)} validation errors, {len(issues) - len(errs)} warnings")
        for i in issues:
            st.write(str(i))
        st.markdown("Rebuild every derived artefact (participant package, scoring reference, Kaggle files, flag registry, cards):")
        if st.button("Run scripts/build_challenge.py"):
            out = subprocess.run([sys.executable, str(paths.ROOT / "scripts" / "build_challenge.py")], capture_output=True,
                                 text=True, cwd=paths.ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            st.code(out.stdout + out.stderr)
        st.markdown(f"Flag registry present: **{paths.FLAG_REGISTRY.exists()}** · FLAG_HMAC_SECRET configured: "
                    f"**{bool(os.environ.get('FLAG_HMAC_SECRET')) and os.environ.get('FLAG_HMAC_SECRET') != 'change-me'}**")

    with tabs[1]:
        st.markdown("Paper projection of the **VERIFIED** graph. Colours: green base, red target, orange canonical "
                    "intermediates, blue alternative-path nodes, grey decoys.")
        canon = paths.read_json(paths.CANONICAL_PATH)
        st.graphviz_chart(_paper_dot(build_graph(records, {"VERIFIED"}), roles, canon["path"]), width="stretch")
        nodes = pd.DataFrame([{k: v for k, v in n.items() if k in ("id", "type", "participant_id", "title", "label", "year", "domain")} for n in records["nodes"]])
        st.markdown("**Nodes**")
        t = st.multiselect("Node types", sorted(nodes.type.unique()), default=sorted(nodes.type.unique()))
        st.dataframe(nodes[nodes.type.isin(t)], hide_index=True, width="stretch")
        edges = pd.DataFrame([{"id": e["id"], "source": e["source"], "type": e["type"], "target": e["target"], "status": e["status"],
                               "explanation": e["explanation"]} for e in records["edges"]])
        st.markdown("**Edges**")
        c1, c2 = st.columns(2)
        ty = c1.multiselect("Relationship types", sorted(edges.type.unique()))
        stt = c2.multiselect("Statuses", sorted(edges.status.unique()))
        mask = pd.Series(True, index=edges.index)
        if ty:
            mask &= edges.type.isin(ty)
        if stt:
            mask &= edges.status.isin(stt)
        view = edges[mask]
        st.dataframe(view, hide_index=True, width="stretch")
        st.download_button("Export master graph (JSON)", json.dumps(records, indent=2, ensure_ascii=False), "master_graph.json")

    with tabs[2]:
        canon = paths.read_json(paths.CANONICAL_PATH)
        st.subheader("Canonical path (secret)")
        st.markdown(" → ".join(f"**{p}**" for p in canon["path_participant_ids"]) + f"  ({canon['transition_count_secret']} transitions)")
        st.caption(canon["why_this_path"])
        for tr in canon["transitions"]:
            with st.expander(f"{tr['from']} → {tr['to']}"):
                st.write(tr["narrative"])
                st.write(tr["supporting_edges"])
        alts = paths.read_json(paths.ALTERNATIVE_PATHS)
        st.subheader("Verified alternative paths")
        for a in alts["paths"]:
            with st.expander(f"{a['id']} · {a['label']}: " + " → ".join(a["path_participant_ids"])):
                st.write(a["notes"])
                st.write(a["supporting_edges"])
        st.caption(alts["review_process"])
        fa = paths.read_json(paths.FINAL_ANSWER)
        st.subheader("Hidden base–target connection (answer key only)")
        st.write(fa["hidden_connection"]["statement"])
        st.json(fa["hidden_connection"], expanded=False)

    with tabs[3]:
        dec = paths.read_json(paths.DECOYS)
        for d in dec["decoys"]:
            with st.expander(f"{d['participant_id']} · {d['internal_id']}"):
                st.markdown(f"**Surface similarity:** {d['surface_similarity']}")
                st.markdown(f"**Why misleading:** {d['why_misleading']}")
                st.markdown(f"**Legitimate relations:** {d['legitimate_relations']}")
                st.markdown(f"**Teaching point:** {d['teaching_point']}")
                st.write("Decoy-induced false edges:", d["decoy_induced_false_edges"])
        st.caption(dec["default_rule"])

    with tabs[4]:
        from .document_reader import extract_text, find_invisible_spans, scan_for_instructions

        inj = paths.read_json(paths.INJECTIONS)
        st.markdown(inj["_comment"])
        st.dataframe(pd.DataFrame([{k: a[k] for k in ("id", "difficulty", "host_card_participant_id", "text", "induced_edge")} for a in inj["annotations"]]),
                     hide_index=True, width="stretch")
        if st.button("Run extraction check on all cards"):
            rows = []
            for pdf in sorted(paths.CARDS_DIR.glob("P*.pdf")):
                text = extract_text(pdf)
                rows.append({"card": pdf.stem, "invisible_spans": len(find_invisible_spans(pdf)),
                             "instruction_flags": len(scan_for_instructions(text)),
                             "markers_found": [a["id"] for a in inj["annotations"] if a["detection_marker"] in " ".join(text.split())]})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    with tabs[5]:
        ids = [e["id"] for e in records["edges"]]
        label = {e["id"]: f"{e['id']}: {e['source']} -{e['type']}-> {e['target']} [{e['status']}]" for e in records["edges"]}
        pick = st.selectbox("Edge", ids, format_func=lambda i: label[i])
        e = next(x for x in records["edges"] if x["id"] == pick)
        st.markdown(f"**Explanation:** {e['explanation']}")
        if e.get("reviewer_notes"):
            st.info(e["reviewer_notes"])
        for ev in e["evidence"]:
            st.json(ev)

    with tabs[6]:
        from graph.pipeline import run_pipeline

        papers = sorted((n for n in records["nodes"] if n["type"] == "PAPER"), key=lambda n: n["participant_id"])
        opts = {f"{p['participant_id']} {p['authors'][0].split()[-1]} {p['year']}": p["id"] for p in papers}
        keys = list(opts)
        canon = paths.read_json(paths.CANONICAL_PATH)
        c1, c2 = st.columns(2)
        a = c1.selectbox("From", keys, index=[opts[k] for k in keys].index(canon["base"]["internal_id"]))
        b = c2.selectbox("To", keys, index=[opts[k] for k in keys].index(canon["target"]["internal_id"]))
        if st.button("Run Stages 1-4"):
            res = run_pipeline(opts[a], opts[b], paths.read_json(paths.FINAL_ANSWER))
            st.subheader("Stage 1 · ranked paths (PoG-inspired)")
            st.dataframe(pd.DataFrame([{"score": round(p.score, 3), "path": " → ".join(g.nodes[n]["participant_id"] for n in p.nodes)} for p in res.stage1[:10]]),
                         hide_index=True, width="stretch")
            st.subheader("Stage 2 · diverse alternatives (EoG-inspired)")
            st.dataframe(pd.DataFrame([{"mmr": round(d.mmr, 3), "quality": round(d.quality, 3), "domains": d.domains,
                                        "max_sim": round(d.max_similarity, 2), "path": " → ".join(g.nodes[n]["participant_id"] for n in d.path.nodes)} for d in res.stage2]),
                         hide_index=True, width="stretch")
            st.subheader("Stage 3 · explained relations (Hyvönen-inspired)")
            for r in res.stage3[:6]:
                st.markdown(f"- **{r.pattern}** · status `{r.status}` · defensible={r.defensible} · interestingness {r.interestingness}")
                st.caption(r.explanation)
            st.subheader("Stage 4 · application report")
            if res.stage4_skipped_reason:
                st.warning(res.stage4_skipped_reason)
            for rep in res.stage4:
                st.markdown(f"**{rep.application_label}** operationalises *{rep.principle_statement}*")
                st.markdown("Research usage: " + ", ".join(f"{u['participant_id']} ({u['method']})" for u in rep.research_usage))
                for i in rep.implementation:
                    st.markdown(f"- {i['relation']} → {i['to']}: {i['how']}")
                st.markdown("**Limitations / differences:**")
                for lim in rep.limitations:
                    st.markdown(f"- {lim}")
                st.markdown(f"Lineage claim: **{rep.lineage_claim}**")

    with tabs[7]:
        with st.form("team"):
            name = st.text_input("Team name")
            members = st.text_input("Members (comma separated)")
            if st.form_submit_button("Create team"):
                try:
                    t = store.create_team(name, [m.strip() for m in members.split(",") if m.strip()])
                    st.success(f"Team {t['team_id']} created. Give them this code (shown once): ")
                    st.code(t["code"])
                except ValueError as exc:
                    st.error(str(exc))
        teams = store.teams()
        if teams:
            st.dataframe(pd.DataFrame([{k: v for k, v in t.items() if k != "code_sha256"} for t in teams.values()]),
                         hide_index=True, width="stretch")

    with tabs[8]:
        cfg = paths.load_config()
        split = st.radio("Split", ["public", "private", "all"], horizontal=True)
        lb = pd.DataFrame(store.best_scores(split, cfg["final_submission"].get("deadline")))
        st.markdown("**Best valid score per team (before deadline)**")
        st.dataframe(lb, hide_index=True, width="stretch")
        subs = store.graph_submissions()
        if subs:
            flat = []
            for s in subs:
                row = {"team_id": s["team_id"], "submitted_at": s["submitted_at"], "edges": s["n_edges"]}
                for sp in ("public", "private", "all"):
                    for k, v in s["scores"][sp].items():
                        row[f"{sp}_{k}"] = v
                flat.append(row)
            df = pd.DataFrame(flat)
            st.dataframe(df, hide_index=True, width="stretch")
            st.download_button("Export submissions (CSV)", _csv(df), "graph_submissions.csv")
            st.download_button("Export leaderboard (CSV)", _csv(lb), f"leaderboard_{split}.csv")

    with tabs[9]:
        q = store.review_queue()
        if not q:
            st.info("No participant-proposed edges awaiting review.")
        reviewer = st.text_input("Reviewer name (required)")
        for i, item in enumerate(q):
            with st.expander(f"[{item['status']}] {item['edge']} · {item['team_id']} · organiser class: {item['organiser_class']}"):
                st.markdown(f"**Team evidence:** {item['evidence_reference']}")
                c1, c2 = st.columns(2)
                if item["status"] == "PENDING":
                    if c1.button("Accept (verified)", key=f"acc{i}"):
                        store.decide_review(i, "ACCEPTED", reviewer)
                        st.rerun()
                    if c2.button("Reject", key=f"rej{i}"):
                        store.decide_review(i, "REJECTED", reviewer)
                        st.rerun()
        acc = store.accepted_additions()
        if acc:
            st.markdown(f"Accepted additions (now reference edges): {acc}")
            st.caption("Rebuild (tab 1) and re-upload the Kaggle solution so Kaggle matches the local scorer.")

    with tabs[10]:
        finals = store.final_submissions()
        if not finals:
            st.info("No final submissions yet.")
        rows = []
        for tid, rec in finals.items():
            ev = rec["evaluation"]
            rows.append({"team_id": tid, "submitted_at": rec["submitted_at"], "target": rec["submission"]["target_id"],
                         "application": rec["submission"]["application"], "auto_result": ev["result"],
                         "application_status": ev["application_status"],
                         "principle_advisory": f"{ev['principle_advisory_score']}/{ev['principle_advisory_max']}",
                         "final_result": rec.get("organiser_review", {}).get("final_result", ""), "flag": rec.get("flag")})
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, hide_index=True, width="stretch")
            st.download_button("Export final flags (CSV)", _csv(df), "final_flags.csv")
            tid = st.selectbox("Review team", list(finals))
            rec = finals[tid]
            st.json(rec["submission"])
            res = st.selectbox("Organiser decision", ["", "CORRECT", "PARTIAL", "INCORRECT"])
            note = st.text_input("Review note")
            if st.button("Save decision") and res:
                store.update_final_review(tid, final_result=res, note=note)
                st.rerun()

    with tabs[11]:
        released = set(store.released_hints())
        for h in all_hints():
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"**Hint {h['id']}** (suggested minute {h['suggested_release_minute']}): {h['text']}")
            if h["id"] in released:
                c2.success("released")
            elif c2.button("Release", key=f"h{h['id']}"):
                store.release_hint(h["id"])
                st.rerun()

    with tabs[12]:
        from scoring.graph_scorer import GraphScorer

        from .document_reader import extract_text
        from .naive_assistant import guarded_extract, naive_extract

        st.markdown("What happens when an AI assistant reads the challenge cards and believes everything it sees?")
        if st.button("Run naive vs guarded extraction"):
            texts = {p.stem: extract_text(p) for p in sorted(paths.CARDS_DIR.glob("P*.pdf"))}
            naive = naive_extract(texts)
            guarded, quarantined = guarded_extract(texts)
            scorer = GraphScorer.from_answer_key(store.accepted_additions())
            st.markdown("**Naive assistant adds:**")
            st.dataframe(pd.DataFrame(naive), hide_index=True, width="stretch")
            ref = sorted(t for t, c in scorer.classes.items() if c == "reference")
            honest = scorer.score(ref[:20]).metrics["all"]
            fooled = scorer.score(ref[:20] + [(e["source_id"], e["target_id"], e["relationship_type"]) for e in naive]).metrics["all"]
            st.markdown(f"A team with 20 correct edges scores **{honest.weighted_f1:.3f}**. Adding the naive assistant's "
                        f"edges drops it to **{fooled.weighted_f1:.3f}** (injection weight ×{scorer.weights['injection_induced']}).")
            st.markdown("**Guarded pipeline quarantined:**")
            st.write(quarantined)
            st.write(f"Guarded proposals (all AI_PROPOSED): {len(guarded)}")
