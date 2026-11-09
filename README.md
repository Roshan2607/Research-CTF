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
  * Runs through the exact same flag validation, cooldown, and submission pipeline as competition levels.

---

## Backend Architecture & Data Model (Section A)

### 1. Backend Architecture
The backend is built around a secure server-side model with Python + JSON storage:
* **Separation of Concerns**: Protected answer registries, canonical paths, and HMAC tokens reside solely on the server side (`data/organiser/`, `data/answer_key/`).
* **Multi-Process Concurrency**: File access is synchronized using a reentrant cross-process file lock (`fcntl.flock`) paired with an in-process thread `threading.RLock()`.
* **Atomic JSON Persistence**: All state mutations are written to temporary files (`.tmp`), flushed to disk (`fsync`), and atomically swapped (`os.replace`).

### 2. JSON Storage Structure (`data/submissions/event_state.json`)
```json
{
  "teams": {
    "TEAM01": {
      "team_id": "TEAM01",
      "name": "Alpha Team",
      "cluster": "Hidden Structures: Networking × Evolutionary Biology",
      "is_demo": false,
      "salt": "<hex-salt>",
      "password_hash": "<pbkdf2-hmac-sha256>",
      "created_at": "2026-11-09T11:00:00+00:00"
    }
  },
  "graphs": {
    "TEAM01": {
      "team_id": "TEAM01",
      "edges": [
        {
          "source_id": "P01",
          "target_id": "P02",
          "relationship_type": "EXTENDS",
          "evidence_reference": "Sec. 2",
          "added_at_level": 1
        }
      ],
      "snapshots": {
        "1": {
          "level": 1,
          "submitted_at": "2026-11-09T11:15:00+00:00",
          "edges": [...],
          "nodes": ["P01", "P02"],
          "csv_text": "..."
        }
      }
    }
  },
  "drafts": {
    "TEAM01:1": "source_id,target_id,relationship_type,evidence_reference\n..."
  },
  "attempts": {
    "TEAM01:1": [
      {
        "at": "2026-11-09T11:05:00+00:00",
        "answer": "wrong guess",
        "correct": false,
        "counted": true
      }
    ]
  },
  "submissions": {
    "TEAM01:1": {
      "team_id": "TEAM01",
      "level": 1,
      "submitted_at": "2026-11-09T11:15:00+00:00",
      "csv": "...",
      "graph_score": {"points": 14.5, "weighted_f1": 0.9667},
      "flag_correct": true,
      "flag_points": 10,
      "submitted_flag": "tree reconstruction",
      "explanation": "Detailed methodology...",
      "manual_adjustment": 0.0,
      "organiser_notes": "",
      "locked": true,
      "edge_count": 5
    }
  },
  "audit": [...],
  "session_tokens": {...},
  "admin_tokens": {...}
}
```

### 3. Team & Cluster Data Model
* **Team Identifiers**: Uppercase alphanumeric strings (3–20 chars, matching `[A-Z0-9_-]{3,20}`).
* **Passwords**: Salted PBKDF2-HMAC-SHA256 digests (minimum 8 chars, 180,000 iterations).
* **Cluster Assignment**: Validated against released clusters in `data/event_content.csv` plus `"Level 0 Demo"`.
* **Level Progression**: Tracked per team as `(completed_levels, current_level)` based on locked submissions.

### 4. Flag Validation Rules
* **Unlimited Attempts**: Teams may submit flag attempts freely prior to level lock.
* **Immediate Feedback**: Instant correct/incorrect status with point and cooldown notifications.
* **Free Attempts**: The first 5 wrong attempts per team per level are free of penalty.
* **Penalty Scaling**: Starting on the 6th wrong attempt, each wrong attempt deducts 1 flag point from the 10 available flag points.
* **30-Second Cooldown**: Applies after *every* wrong attempt (including the first five).
* **Cooldown Rejection Rule**: Attempts during an active cooldown are rejected with remaining wait time and **never** increment the attempt counter or incur additional penalties.
* **Server-Side Registry Protection**: Expected answers are normalized server-side; correct answers never disclose the answer registry.

### 5. Submission & Locking Workflow
* **One Submission per Level**: Exactly one final submission per team per level.
* **Atomic Locking**: Checked and persisted under process file lock; simultaneous final submissions cannot both succeed.
* **Pre-conditions**:
  1. At least one flag attempt must have been logged for the level.
  2. A non-empty cumulative knowledge graph CSV must be provided.
  3. A written methodology explanation must be provided.
* **Immutability**: Once submitted, the backend sets `locked: True`. Subsequent edits to the graph, flag, or explanation for that level are strictly rejected.
* **Non-Locking Failures**: Validation errors (e.g. missing fields) return clear error messages and never lock the level.

### 6. Graph Persistence Strategy
* **Continuous Cumulative Graph**: Teams construct one persistent knowledge graph spanning all levels.
* **Cross-Level Extension**: Locking level $N$ snapshots the graph submitted for level $N$; the team may continue adding new edges and expanding the graph in level $N+1$.
* **Immutable Snapshots**: `get_graph_snapshot(team_id, level)` returns the frozen graph snapshot submitted for that level; subsequent edge edits cannot mutate previous snapshots.

### 7. Key Module Interfaces
* **`event_core.py`**:
  * `create_team(team_id, name, password, cluster, is_demo)`
  * `authenticate(team_id, password)`
  * `team_progress(team_id) -> tuple[list[int], int | None]`
  * `attempt_flag(team, level, answer) -> dict`
  * `flag_status(team, level) -> dict`
  * `get_team_graph(team_id) -> TeamKnowledgeGraph`
  * `save_team_graph(team_id, graph)`
  * `get_graph_snapshot(team_id, level) -> dict | None`
  * `finalise(team, level, csv_text, flag_correct, graph_score, submitted_flag, explanation) -> dict`
  * `admin_snapshot() -> dict`
* **`scoring/flag_validator.py`**:
  * `LevelFlagValidator(cooldown_seconds, free_wrong_attempts, flag_points_per_level, penalty_per_attempt)`
  * `evaluate_attempt(...) -> dict`
  * `compute_status(...) -> dict`
  * `normalise_flag(s) -> str`
* **`challenge/submission.py`**:
  * `LevelSubmissionService(state_path)`
  * `submit_level(team_id, level, graph_csv, explanation, ...) -> dict`
  * `is_locked(team_id, level) -> bool`
  * `get_submission(team_id, level) -> dict | None`
  * `get_submitted_graph_snapshot(team_id, level) -> dict | None`
* **`challenge/graph_store.py`**:
  * `TeamKnowledgeGraph(team_id, data)`
  * `validate_graph_structure(edges, allowed_papers, allowed_relations)`

### 8. Configuration Options (`config/challenge_config.json`)
* `num_levels`: Total levels in the CTF (default: `4`).
* `clusters`: Registered cluster names.
* `rules.free_wrong_attempts`: Free incorrect flag attempts per level (default: `5`).
* `rules.penalty_after_free`: Penalty point per wrong attempt starting from the 6th (default: `1.0`).
* `rules.cooldown_seconds`: Cooldown duration after wrong attempt (default: `30`).
* `rules.graph_points_per_level`: Graph scoring maximum points per level (default: `15.0`).
* `rules.flag_points_per_level`: Flag maximum points per level (default: `10.0`).
* `rules.submission_limit_per_level`: Maximum final submissions allowed per level (default: `1`).
* `demo_team`: Level 0 demo team credentials and demo flag (`FLAG{TRIE}`).

### 9. Known Limitations of JSON Persistence & Deployment Constraints
* **Single-Node Filesystem**: JSON persistence relies on POSIX file locking (`fcntl.flock`) and atomic file replacement (`os.replace`). It operates safely across multiple processes on a single host (such as multiple Streamlit workers), but is **not** distributed across multiple separate servers or network file shares without POSIX flock support.
* **In-Memory Cache Coherence**: Each worker process re-reads `event_state.json` inside locked sections to guarantee view consistency. In high-concurrency environments (>50 simultaneous write operations/sec), an enterprise relational database (e.g. PostgreSQL) would be recommended.

---

## Key File Structure

```
├── event_core.py                 # Core business logic: auth, drafts, cooldowns, penalties, locking
├── event_portal.py               # Participant web portal (4 tabs)
├── event_admin.py                # Protected organiser dashboard & manual review console
├── challenge/
│   ├── graph_store.py            # Persistent team knowledge graph data model & snapshot manager
│   ├── submission.py             # LevelSubmissionService & ParticipantBackend facade
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
│   └── flag_validator.py         # LevelFlagValidator & HMAC flag token validator
└── tests/                        # Comprehensive pytest test suite (151 tests)
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
