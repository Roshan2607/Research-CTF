# Proof of Thought

**Proof of Thought (PoT)** is an interdisciplinary research-literacy Knowledge Graph CTF platform. Participant teams analyze academic excerpts across multiple disciplines, reconstruct cumulative, evidence-backed knowledge graphs, and discover hidden cross-domain principles across progressive levels.

---

## Quick Start (Organisers)

```bash
# 1. Setup virtual environment
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
copy .env.example .env            # macOS/Linux: cp .env.example .env
```

Edit `.env` and set:
* `ORGANISER_PASSWORD`: Admin password (minimum 12 characters).
* `FLAG_HMAC_SECRET`: Random 64-character hex secret for the Level 4 final-discovery tokens; then run `python scripts/build_challenge.py`.

> **Security Note:** Never commit `.env` or runtime data files (`data/*.csv`, `data/*.jsonl`) to git.

---

## Running the Event

Run both Streamlit applications during the workshop:

### 1. Organiser Admin Console (Localhost only)
```bash
python -m streamlit run event_admin.py --server.address 127.0.0.1 --server.port 8504
```
* **URL:** `http://127.0.0.1:8504`
* **Features:** Live leaderboard, team registration, explanation review, manual score adjustments, Event Controls (level gate, hints, flag overrides, final-discovery review, team reset, difficulty alerts) and audit logs.

### 2. Participant Portal (LAN / Event Network)
```bash
python -m streamlit run event_portal.py --server.address 0.0.0.0 --server.port 8503
```
* **Localhost:** `http://127.0.0.1:8503`
* **LAN Participants:** `http://<organiser-ip>:8503`
* **Features:** Exactly 4 tabs:
  1. **Start:** Briefing, level status, and accepted relationship vocabulary.
  2. **Papers:** Released papers, abstracts, links, PDF challenge cards, and optional hints.
  3. **Knowledge Graph:** Interactive edge builder, CSV import (with Codex support), cumulative edge table, Graphviz diagram, and CSV export.
  4. **Submit:** Flag validation with live cooldown feedback, cumulative graph preview, methodology explanation form, and level lock.

---

## Event Rules & Scoring Model

* **100 points total**: 4 competition levels x 25 points (15 graph + 10 flag/discovery). Level 0 is an unscored, clearly synthetic warm-up.
* **Papers are released by role, not by ID** (one verified 15-paper corpus): L1 4 papers, L2 5, L3 4, L4 2. Every level has scoreable reference edges (cumulative 5 / 16 / 26 / 41).
* **Graph points** are computed **on the server** when a level is locked: weighted typed-edge F1 over the papers released so far. Edges planted by hidden AI-directed instructions cost 3x, but only once the card carrying the instruction is released.
* **Flags (Levels 1-3)**: a few words are enough - answers are matched by keyword groups, not exact strings. A correct flag (or a named organiser override) is required to lock a level.
  * The first 5 wrong attempts per level are free, then each costs 0.5 points (at most 5 per level).
  * Cooldown after each wrong attempt: 10 s, 10 s, then 30 s.
  * Hints: a 3-rung ladder per level, unlocked after 2 / 4 / 6 wrong attempts. Only rung 3 costs 1 point. Organisers can release any rung for free.
* **Level 4 = one-shot final discovery**: hidden paper, shared principle, real-world application, evidence and limitations. It is validated against HMAC tokens (3 + 2 automatic points) and organiser-reviewed (up to 5 points). Results are hidden until the deadline.
* **Cumulative graph**: one graph across all levels. It stays editable until the final lock, and each locked level keeps an immutable snapshot of the graph it was scored on.
* **Organiser controls**: level gate, hint releases, flag overrides, final-discovery review, team reset, difficulty alerts, CSV export.

See [EVENT_PILOT_GUIDE.md](EVENT_PILOT_GUIDE.md) for the release plan, answers and difficulty targets (organiser only).

---

## Key File Structure

```
├── event_core.py                 # Core business logic: auth, drafts, cooldowns, penalties, locking
├── event_portal.py               # Participant web portal (4 tabs)
├── event_admin.py                # Protected organiser dashboard & manual review console
├── challenge/
│   ├── cards.py                  # Challenge card PDF generator (ReportLab)
│   ├── participant_data.py       # Participant data loading & isolation whitelist
│   └── submission_store.py       # Legacy atomic JSON storage engine
├── config/
│   └── challenge_config.json     # Workshop parameters & false-positive scoring weights
├── data/
│   ├── event_content.csv         # Level questions, flag answers, papers, and hints
│   ├── corpus_seed.json          # Master paper seed manifest
│   ├── participant/cards/        # 1-page PDF challenge cards (P01..P14.pdf)
│   └── answer_key/               # Canonical paths, decoys, and injection annotations
├── scoring/
│   ├── graph_scorer.py           # Weighted typed-edge graph scoring engine
│   └── flag_validator.py         # HMAC flag token validator
└── tests/                        # pytest suite (engine, live content, calibration, apps)
```

---

## Maintenance & Testing Commands

```bash
# Run full automated test suite
python -m pytest

# Regenerate challenge cards (requires ReportLab)
python scripts/build_challenge.py

# Verify quoted evidence passages against Open Access sources
python scripts/verify_evidence.py
```
