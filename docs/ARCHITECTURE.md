# Architecture

A deliberately small proof of concept: Python, NetworkX, JSON/CSV, pandas, Streamlit, a local scorer and a
Kaggle-compatible metric. There is no database, no external service, no reinforcement learning and no LLM dependency.

## Data layers

```text
data/
├── corpus_seed.json, source_manifest.json   bibliographic source of truth (OpenAlex + Crossref, with provenance)
├── organiser/            ┐  1. ORGANISER MASTER DATA (never served)
│   ├── master_graph.json │     heterogeneous graph: 47 nodes, 126 typed edges, each with evidence
│   └── hints.json        │     (released hints only leave via challenge.hints)
├── answer_key/           │
│   ├── canonical_path.json, alternative_paths.json, decoys.json, injection_annotations.json
│   ├── final_answer.json, scoring_policy.json
│   ├── scoring_reference.json         (generated; classified candidate universe)
│   ├── flag_registry.json             (generated; HMAC tokens only; git-ignored)
│   └── kaggle_solution.csv            (generated; host-only; git-ignored)
├── participant/          ┘  2. PARTICIPANT DATA (the only directory the participant UI reads)
│   ├── participant_papers.json, relationship_vocabulary.json, challenge_info.json
│   └── cards/P01..P14.pdf             (wrapper cards incl. synthetic annotation layer)
├── submissions/             3. SUBMISSION DATA (runtime, git-ignored; UL_SUBMISSIONS_DIR overrides)
│   └── teams, graph_submissions.jsonl, review_queue, accepted_additions, hint_state, final_submissions
└── samples/                 sample edge-list submissions (initial / revised / malformed) + Kaggle format
```

The participant package is **generated** from a field whitelist (`challenge/participant_data.py`). Organiser
annotations, concept nodes, edges and roles cannot be copied into it by accident. Participant loaders refuse any path
outside `data/participant`.

## Modules

| Module | Role |
|---|---|
| `graph/schema.py` | Data dictionary: node types, 10 relationship types (8 required + `IN_DOMAIN`, `EMBODIES_PRINCIPLE`), claim kinds, signatures, symmetric/temporal rules, verification states |
| `graph/builder.py` | **Stage 0**: records → `networkx.MultiDiGraph`; paper and concept projections |
| `graph/validation.py` | Schema and provenance validation; `promote_edge` (the only path to `VERIFIED`, needs a named human) |
| `graph/path_discovery.py` | **Stage 1** (PoG-inspired): beam search, claim-kind transition quality, relevance pruning |
| `graph/alternative_paths.py` | **Stage 2** (EoG-inspired, no RL): penalised re-search + MMR diversity + domain bonus |
| `graph/relationship_explainer.py` | **Stage 3** (Hyvönen-inspired): explained cross-domain relations via shared principle/method/problem/chains; always `AI_PROPOSED` |
| `graph/application_discovery.py` | **Stage 4**: evidence-backed application report, gated on a defensible Stage 3 relation; `ApplicationSearch` interface stub for external search |
| `graph/pipeline.py` | Runs Stages 0 → 1 & 2 → 3 → 4 (organiser only) |
| `scoring/reference.py` | Candidate universe (543 typed edges over 15 papers) and organiser classification; stable hash Public/Private split |
| `scoring/weighted_metrics.py` | Weighted precision / recall / F1 with safe zero handling |
| `scoring/graph_scorer.py` | Submission parsing/validation and scoring; participant view = 3 aggregate numbers |
| `scoring/kaggle_metric.py`, `kaggle_format.py` | Kaggle `score()` (pandas only) and edge-list ↔ grid conversion |
| `scoring/flag_validator.py` | HMAC registry, one-shot final submission, deadline-gated feedback, team-bound flags |
| `challenge/submission.py` | **Participant backend facade**: the only bridge from the participant UI to protected data |
| `challenge/submission_store.py` | Teams (hashed codes), submissions, rate limits, best scores, review queue, hints, finals |
| `challenge/cards.py` | Uniform PDF wrapper cards with a fixed-height annotation block (white-on-white injections) |
| `challenge/document_reader.py` | Text extraction, invisible-span detection, instruction scanning, untrusted-data envelope, safe LLM message composition |
| `challenge/naive_assistant.py` | Deterministic "gullible AI" vs guarded extraction (demo + tests) |
| `challenge/participant_view.py`, `app.py` | Participant Streamlit UI |
| `challenge/organiser_view.py`, `organiser_app.py` | Organiser console (localhost + password) |

## Security model (proportionate to a workshop)

* **Server-side answer key.** Streamlit renders on the server, and the browser receives only rendered widgets. The
  participant UI imports neither the answer key nor the organiser view (enforced by `tests/test_participant_isolation.py`,
  which inspects imports and source). Static file serving is off; HTTP probes for protected paths return only the app shell.
* **Aggregate scoring only.** Participants see weighted F1, precision and recall on the public split. Base–target edges
  are neutral, so single-edge probing cannot reveal the target. Rate limits, submission caps and the private split
  further limit oracle attacks.
* **Flags.** HMAC-SHA256 with a server-side secret. The registry contains no plaintext and has a key-check token. One
  shot per team, locked, with no feedback before the deadline. Team-bound flag strings.
* **Organiser console.** A separate process bound to 127.0.0.1, behind `ORGANISER_PASSWORD` (constant-time compare).
* **Team identity.** Random codes, stored as SHA-256 hashes.
* **Not in scope:** TLS, multi-host deployment, defence against a participant with OS access to the organiser
  laptop, and file locking across multiple processes (a single Streamlit process with a thread lock is assumed).

## Pipeline concepts and what is *not* claimed

* PoG (Tan et al., WWW 2025): only "explore candidate paths, prune weak or irrelevant ones". No LLM-guided decomposition.
* EoG (Yan et al., ICLR 2026): only "encourage diverse paths". No RL and no reward-model training.
* Hyvönen (J. Web Semantics 2025): only "search and explain interesting relations". Not an autonomous transfer or
  product-discovery system.
* Stage 4 uses organiser-researched application records; live web search is an interface stub (`NoExternalSearch`).
