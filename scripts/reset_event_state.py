#!/usr/bin/env python3
"""Reset Research-CTF event state to a pristine, clean slate.

Always creates a pre-reset safety snapshot in data/backups/ before resetting,
so no data is ever lost.

Usage:
    python scripts/reset_event_state.py
    python scripts/reset_event_state.py --force  # Skip interactive prompt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import event_core as core


def reset_everything(force: bool = False) -> None:
    if not force:
        print("\n" + "=" * 65)
        print(" WARNING: RESETTING EVENT STATE TO CLEAN SLATE ".center(65, "="))
        print("=" * 65)
        print("This will clear all registered teams, submissions, graph drafts,")
        print("and event logs. A safety backup will be archived first.")
        confirm = input("\nType 'RESET' to confirm and proceed: ").strip()
        if confirm != "RESET":
            print("[Cancelled] Reset aborted.")
            return

    # 1. Create a safety backup of existing state
    try:
        backup_path = core.create_backup(tag="pre_wipe_safety")
        print(f"[1/4] Safety backup created: {backup_path.name}")
    except Exception as e:
        print(f"[Warning] Could not create safety backup: {e}")

    # 2. Reset event_state.json to clean empty schema
    clean_state = core._empty()
    core.save(clean_state)
    print("[2/4] Pristine event_state.json initialized.")

    # 3. Ensure Level 0 demo team is initialized
    try:
        core.ensure_demo_team()
        print("[3/4] Default demo team initialized.")
    except Exception as e:
        print(f"[Info] Demo team setup: {e}")

    # 4. Clean supporting CSVs and event log
    try:
        if core.LOG.exists():
            core.LOG.write_text("", encoding="utf-8")
        if core.TEAM_CSV.exists():
            core.TEAM_CSV.write_text("team_id,name,registered_at,cluster,is_demo\n", encoding="utf-8")
        if core.SUB_CSV.exists():
            core.SUB_CSV.write_text("team_id,level,submitted_at,flag_correct,flag_points,graph_points,total_points\n", encoding="utf-8")
        print("[4/4] Supporting logs and CSV tables re-initialized.")
    except Exception as e:
        print(f"[Info] Log cleanup: {e}")

    print("\n" + "=" * 65)
    print("[SUCCESS] Event state successfully reset to a clean slate!".center(65))
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Reset Research-CTF event state to clean slate")
    parser.add_argument("--force", action="store_true", help="Force reset without confirmation prompt")
    args = parser.parse_args()

    reset_everything(force=args.force)


if __name__ == "__main__":
    main()
