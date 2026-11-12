#!/usr/bin/env python3
"""Event State Backup & Disaster Recovery CLI for Research-CTF.

Commands:
    # 1. Create an immediate timestamped snapshot:
    python scripts/backup_event.py --create [optional_tag]

    # 2. List all existing snapshots:
    python scripts/backup_event.py --list

    # 3. Restore state from a specific snapshot:
    python scripts/backup_event.py --restore data/backups/event_state_20261112_111530_manual.json

    # 4. Run automated continuous backup daemon (e.g. every 5 minutes):
    python scripts/backup_event.py --auto --interval 300
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import event_core as core


def create_snapshot(tag: str = "manual") -> None:
    p = core.create_backup(tag=tag)
    sz = p.stat().st_size / 1024
    print(f"[OK] Backup created successfully: {p} ({sz:.1f} KB)")


def list_snapshots() -> None:
    backups = core.list_backups()
    if not backups:
        print("[Info] No backups found in data/backups/.")
        return

    print("\n" + "=" * 78)
    print(f"{'Filename':<38} {'Created (UTC)':<20} {'Teams':<7} {'Subs':<6} {'Size'}")
    print("=" * 78)
    for b in backups:
        print(f"{b['filename']:<38} {b['created_at']:<20} {b['teams']:<7} {b['submissions']:<6} {b['size_kb']} KB")
    print("=" * 78)
    print(f"Total backups: {len(backups)}")


def restore_snapshot(path_str: str) -> None:
    target = Path(path_str)
    if not target.is_absolute():
        target = ROOT / target

    if not target.exists():
        print(f"[Error] Target backup file not found: {target}")
        sys.exit(1)

    print(f"[Info] Restoring state from: {target}...")
    try:
        new_data = core.restore_backup(target)
        t_cnt = len(new_data.get("teams", {}))
        s_cnt = len(new_data.get("submissions", {}))
        print(f"[SUCCESS] State restored successfully! (Teams: {t_cnt}, Submissions: {s_cnt})")
        print("A safety snapshot of the previous state was saved with tag 'pre_restore_safety'.")
    except Exception as e:
        print(f"[Failed] Restore failed: {e}")
        sys.exit(1)


def run_auto_daemon(interval: int = 300) -> None:
    print(f"[Daemon] Starting automatic backup daemon (snapshot every {interval}s). Press Ctrl+C to stop.")
    try:
        while True:
            core.create_backup(tag="auto_interval")
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Automatic snapshot created.")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[Daemon] Stopped.")


def main():
    parser = argparse.ArgumentParser(description="Research-CTF State Backup & Disaster Recovery Tool")
    parser.add_argument("--create", nargs="?", const="manual", help="Create a timestamped snapshot with an optional tag")
    parser.add_argument("--list", action="store_true", help="List all available state backups")
    parser.add_argument("--restore", type=str, help="Restore state from specified backup file path")
    parser.add_argument("--auto", action="store_true", help="Run as a standing backup daemon")
    parser.add_argument("--interval", type=int, default=300, help="Backup interval in seconds for --auto (default: 300s)")
    args = parser.parse_args()

    if args.create is not None:
        create_snapshot(args.create)
    elif args.list:
        list_snapshots()
    elif args.restore:
        restore_snapshot(args.restore)
    elif args.auto:
        run_auto_daemon(args.interval)
    else:
        # Default: list backups
        list_snapshots()


if __name__ == "__main__":
    main()
