# Uncharted Literature — Incremental multi-cluster event

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

## Graph behaviour

Each team has one cumulative graph. At a level, they can connect any two distinct papers released so far. The five allowed relationship types remain enforced; paper-pair selection is unrestricted, and temporal direction checks are disabled for this event workflow. Earlier-level edges are included in later cumulative snapshots and cannot be deleted through the participant UI. Current-level edges can be deleted before that level is submitted. A level submission locks the cumulative graph and advances the team if at least one non-empty flag attempt has been submitted. The attempt may be incorrect; a correct answer is not required. On later levels, the cumulative graph may be submitted unchanged.

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
