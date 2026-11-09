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
* `FLAG_HMAC_SECRET`: Random 64-character hex secret for HMAC tokens.

> **Security Note:** Never commit `.env` or runtime data files (`data/*.csv`, `data/*.jsonl`) to git.

---

## Running the Event

Run both Streamlit applications during the workshop:

### 1. Organiser Admin Console (Localhost only)
```bash
python -m streamlit run event_admin.py --server.address 127.0.0.1 --server.port 8504
```
* **URL:** `http://127.0.0.1:8504`
* **Features:** Live team leaderboard, team/cluster registration, explanation review, manual score adjustments (+/- pts), and real-time audit logs.

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

* **100 Points Total**: 4 levels $\times$ 25 points each (15 graph points + 10 flag points per level).
  * **Graph Points (up to 15 pts/level)**: Scored on weighted F1 against reference connections and evidence quality, with optional organiser manual adjustments.
  * **Flag Points (up to 10 pts/level)**: Awarded upon finding the correct level flag.
* **Flag Attempt Rules**:
  * Unlimited attempts with instant correct/incorrect feedback.
  * The first **5 wrong attempts per level are free**.
  * From the **6th wrong attempt, each costs 1 flag point**.
  * A **30-second cooldown** applies after every wrong attempt (attempts during cooldown are rejected without further penalty).
* **Cumulative Knowledge Graph**:
  * One continuous graph carries across all 4 levels.
  * Relationships submitted in prior levels are permanently locked.
  * New edges can be added via dropdowns or CSV upload (Codex-formatted files supported).
* **Level Submissions & Immutability**:
  * Advancing requires submitting at least one flag attempt, the cumulative graph, and a written **explanation** of the discovered connections.
  * Submissions are locked on the backend; once locked, graph edges, flags, and explanations cannot be modified.
* **Level 0 Demo Team**:
  * Facilitator demo team (`is_demo=True`) is excluded from the official scoreboard by default.

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
└── tests/                        # Comprehensive pytest test suite (106 tests)
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
