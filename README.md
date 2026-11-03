# Uncharted Literature

**OpenAI × IEEE CS × Research Et Al**: an AI-assisted interdisciplinary research-literacy workshop with a Knowledge
Graph CTF (3 hours, teams of two).

Participants get 14 real research papers from biology, computer science, networking and signal processing. They
**reconstruct an evidence-backed knowledge graph** of how the papers relate (scored repeatedly), then make **one final
discovery submission**: which paper from another discipline shares a hidden principle with their starting paper, what
that principle is, and which real-world technology operationalises it. Decoy papers and controlled prompt-injection
annotations test whether teams verify evidence rather than trusting surface similarity or AI output.

> **Theme:** *Reconstruction of Hidden Structures from Incomplete Information.*
> This repository is **private** because it contains the answer key (`data/answer_key/`, `docs/ORGANISER_GUIDE.md`,
> `docs/DATA_PROVENANCE.md`). Give participants only the app URL, `docs/PARTICIPANT_GUIDE.md` and the card PDFs.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate                      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                      # macOS/Linux: cp .env.example .env
#   edit .env: FLAG_HMAC_SECRET = output of  python -c "import secrets; print(secrets.token_hex(32))"
#              ORGANISER_PASSWORD = something strong
python scripts/build_challenge.py           # validate graph + build participant package, scoring, Kaggle files, flags, cards
python -m pytest                            # 98 tests
```

Run the apps:

```bash
# participants (LAN): http://<organiser-ip>:8501
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
# organiser console (this machine only)
streamlit run organiser_app.py --server.port 8502 --server.address 127.0.0.1
```

See it all work without clicking: `python scripts/demo_walkthrough.py` writes
[docs/DEMO_TRANSCRIPT.md](docs/DEMO_TRANSCRIPT.md), covering organiser build → neutral corpus → initial graph (F1 0.26 public)
→ injection breakdown → revised graph (0.71) → hidden connection → locked final answer → post-deadline results.

## What is in the box

| Deliverable | Where |
|---|---|
| Streamlit participant app / organiser console | `app.py`, `organiser_app.py`, `challenge/participant_view.py`, `challenge/organiser_view.py` |
| Verified research corpus (14 papers, 4 disciplines) | `data/corpus_seed.json` → `data/source_manifest.json` (OpenAlex + Crossref, `scripts/fetch_metadata.py`) |
| Master heterogeneous knowledge graph (47 nodes, 126 evidence-backed edges) | `data/organiser/master_graph.json`, `graph/` |
| Participant-safe corpus and challenge package | `data/participant/` (generated from a whitelist) |
| Canonical path, alternatives, decoys, injections, final answer | `data/answer_key/` |
| Prompt-injection wrapper cards | `data/participant/cards/P01..P14.pdf`, `challenge/cards.py`, `challenge/document_reader.py` |
| Discovery pipeline Stages 0–4 (PoG / EoG / Hyvönen-inspired) | `graph/builder.py`, `path_discovery.py`, `alternative_paths.py`, `relationship_explainer.py`, `application_discovery.py`, `pipeline.py` |
| Iterative weighted typed-edge F1 scorer | `scoring/graph_scorer.py`, `scoring/reference.py`, `scoring/weighted_metrics.py` |
| Kaggle metric, format and setup | `scoring/kaggle_metric.py`, `scoring/kaggle_format.py`, `kaggle/`, [docs/KAGGLE_SETUP.md](docs/KAGGLE_SETUP.md) |
| One-shot HMAC flag validator | `scoring/flag_validator.py` |
| Sample submissions | `data/samples/` |
| Guides | [Organiser](docs/ORGANISER_GUIDE.md) · [Participant](docs/PARTICIPANT_GUIDE.md) · [Architecture](docs/ARCHITECTURE.md) · [Data provenance](docs/DATA_PROVENANCE.md) |
| Tests and results | `tests/`, [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md) |

## Useful commands

```bash
python scripts/fetch_metadata.py                 # refresh bibliographic metadata from OpenAlex/Crossref (network)
python scripts/verify_evidence.py                # re-check every quoted evidence passage against OA full text (network)
python -m scoring.graph_scorer data/samples/sample_submission_revised.csv   # score an edge list (organiser detail)
python -m scoring.kaggle_format my_edges.csv kaggle_submission.csv          # edge list -> Kaggle grid
```

## Configuration

* `config/challenge_config.json`: false-positive weights (ordinary 1.0, decoy 0.5, injection 3.0, *provisional*),
  submission limits, public/private split, final deadline.
* `.env`: `FLAG_HMAC_SECRET`, `ORGANISER_PASSWORD`, optional `FINAL_DEADLINE`. Never commit it.
* `UL_SUBMISSIONS_DIR`: optional override for where runtime submission data is stored.

## Status and limitations

Working end to end: corpus → graph → participant package → iterative scoring (local and Kaggle-format) → review queue
→ one-shot flag → organiser results. Known limitations:

* Seven papers are paywalled. Their edges rest on abstracts and reference lists, and deeper claims are marked
  `REQUIRES_REVIEW`.
* Some items need a human expert's sign-off before use with students (see ORGANISER_GUIDE §8). The most important is
  confirming the starting paper's grouping algorithm in its full text.
* Kaggle competition creation is manual (the API cannot do it). The local scorer is the source of truth and the fallback.
* Single-process JSON storage: fine for one workshop on one laptop, not for multi-server deployment.
* No live LLM or web-search integration. Stage 4 uses organiser-researched application records behind an interface stub.
