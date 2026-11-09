# Proof of Thought — Incremental multi-cluster event

## Release plan

The event supports multiple clusters. Each team is assigned to one cluster at registration. The starter CSV contains one cluster and 14 papers, released incrementally:

- Level 1: P01–P02 (2 papers)
- Level 2: P03–P06 (4 additional papers; 6 total)
- Level 3: P07–P10 (4 additional papers; 10 total)
- Level 4: P11–P14 (4 additional papers; 14 total)

Edit `data/event_content.csv` to change release levels, challenge-card paths, level questions, accepted flag aliases and hints. The `cluster` column determines which cluster owns each row; the flag question and answer aliases are shared by all paper rows in the same cluster and level.

### Adding clusters

- In the admin portal, open **Create team** and use **Create a new cluster**. Choose a template cluster and enter a new name. The app copies the template cluster's rows into `data/event_content.csv`, giving the new cluster a complete four-level starter configuration.
- To add or customise clusters in Excel, open `data/event_content.csv`. Copy all rows belonging to a cluster, paste them as new rows, and change the `cluster` value on every copied row to the new cluster name. Then edit `level`, `level_title`, `paper_id`, `paper_title`, `challenge_card_path`, `flag_question`, `flag_answers`, and `hints` as needed. Save as CSV (UTF-8).
- The participant app displays only papers whose `paper_id` exists in `data/participant/participant_papers.json`, and challenge-card downloads require a matching PDF in `data/participant/cards/`. Therefore a new cluster can immediately reuse the starter corpus; to introduce genuinely new papers, also add their participant-safe metadata and PDFs to the participant package (then ensure their IDs match the CSV).
- A team's cluster is fixed when the team is created. Create a new team if it must belong to a different cluster.

## Graph & Submission Rules

Each team has one cumulative graph across four levels. At each level, they can connect any two distinct papers released so far:

- **Four Tabs Only**: The participant portal is structured into four tabs:
  1. **Start**: Briefing, current level progress, and accepted relationship vocabulary.
  2. **Papers**: Released papers, abstracts, links, PDF challenge cards, instructions, and hints.
  3. **Knowledge Graph**: Interactive edge builder, CSV import (with Codex format support), cumulative edge table, live Graphviz visualization, and CSV download.
  4. **Submit**: Flag verification, cumulative graph preview, explanation text area, and level lock.
- **Flag Attempts & Penalties**:
  - Flag attempts are unlimited and provide instant feedback.
  - The first **5 wrong attempts per level are free**.
  - Starting from the **6th wrong attempt, each costs 1 flag point** (out of 10 max flag points for that level).
  - A **30-second cooldown** applies after every wrong attempt. Attempts during cooldown are blocked.
- **Level Submissions**:
  - Each level requires at least one flag attempt, the cumulative graph, and a written **explanation** of the graph and reasoning.
  - Submitting locks the graph, flag, and explanation on the backend.
  - Once locked, no further edits to that level's graph, flag, or explanation are permitted.
- **Scoring (100 Points Total)**:
  - Each level awards up to **25 points**: **15 graph points** (evaluated against reference connections) and **10 flag points** (minus wrong-attempt penalties).
  - Across 4 levels: 60 graph points + 40 flag points = 100 points total.
  - Organisers can review explanations and manually adjust graph scores (+/- points) in the admin console.
- **Level 0 Demo Team**:
  - A team can be registered as a demo team; demo teams are excluded from the official leaderboard by default.

## Run on Windows PowerShell

1. Extract the ZIP.
2. Open PowerShell in `Unchartered-Literature-main`.
3. Create and activate the environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

4. Create `.env` from `.env.example`; set `ORGANISER_PASSWORD` to a strong password (at least 12 characters). Do not commit `.env`.
5. Start admin in one terminal:

   ```powershell
   python -m streamlit run event_admin.py --server.address 127.0.0.1 --server.port 8504
   ```

6. Start participant portal in a second terminal:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m streamlit run event_portal.py --server.address 0.0.0.0 --server.port 8503
   ```

Admin: `http://localhost:8504` (keep local). Participant: `http://localhost:8503`. For LAN participants, share `http://<host-IPv4>:8503` after allowing the port through Windows Firewall.

## Data and logs

- `data/event_content.csv`: editable event configuration; duplicate rows with a new `cluster` value to add cluster content.
- `data/teams.csv`: generated team export; passwords are represented only by salts and hashes.
- `data/submissions.csv`: generated locked-submission export with cumulative graph CSV data.
- `data/realtime_events.jsonl`: append-only JSON Lines activity log for team creation, draft saves, flag attempts and submissions.
- `data/submissions/event_state.json`: authoritative application state. Back this file up; the CSV exports are regenerated from it.

The participant and admin apps use long-lived opaque session cookies (14 days) to survive ordinary browser refreshes. The apps wait for the browser cookie component to restore its values before showing the login screen. Signing out revokes the session. The dashboard, submissions and flag/audit views refresh automatically every three seconds while open.

## Important operational notes

- Keep the admin portal bound to `127.0.0.1`; do not expose it to the participant LAN.
- Back up `data/submissions/event_state.json` and `data/realtime_events.jsonl` before and after the event.
- Do not share `teams.csv`, `event_state.json`, `submissions.csv`, or the JSONL log publicly; they contain private team/submission data.
- `event_content.csv` contains organiser-side accepted flag aliases. Do not publish it to participants.
- The app is designed for a single-host pilot. Do not run multiple app instances against the same JSON state file.
