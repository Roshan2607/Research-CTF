# Event data files

- `event_content.csv` is organiser-managed content configuration: one row per paper release, with cluster, level, paper ID/title, challenge-card PDF path, level-wide flag question, accepted answer aliases, and hints. Current pilot uses one cluster and releases 2 / 4 / 4 / 4 papers across Levels 1–4.
- `teams.csv` is an automatically refreshed export of team records. Passwords are **not** stored in plaintext; only salts and PBKDF2 hashes are exported. Treat this file as confidential.
- `submissions.csv` is an automatically refreshed export of locked submissions. `graph_csv` contains the cumulative edge-list CSV for each level snapshot.
- `realtime_events.jsonl` is an append-only event stream. Each line is one JSON object (team creation, draft save, flag attempt, level submission). It is suitable for tailing or later ingestion into a log analysis tool.
- `submissions/event_state.json` is the application's authoritative transactional store. Do not edit the CSV exports by hand; they are regenerated from this JSON state.

Challenge card PDFs live under `data/participant/cards/` and are linked from `event_content.csv`.
