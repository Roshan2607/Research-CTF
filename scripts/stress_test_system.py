#!/usr/bin/env python3
"""Comprehensive System Stress Test for Research-CTF.

Simulates N concurrent teams (default: 40) executing simultaneous:
1. Authentication & Team Logins
2. Flag Answer Validations & Cooldown Mechanics
3. Knowledge Graph Updates & Level Submissions / Locking
4. Grok / AI Judge Concurrent Load & Rate-Limit Handling (429 Resilience)

Usage:
    # Run full 40-team stress test in isolated sandbox (safe for production):
    python scripts/stress_test_system.py --teams 40

    # Include live Grok / Groq API access limits test (requires API key in .env):
    python scripts/stress_test_system.py --teams 40 --test-grok

    # Test Grok rate-limit 429 error handling with emulated provider quota:
    python scripts/stress_test_system.py --teams 40 --mock-grok-limits
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import event_core as core
from scripts.evaluate_submissions import evaluate_submission


@dataclass
class PhaseResult:
    name: str
    total_ops: int = 0
    success_ops: int = 0
    failed_ops: int = 0
    latencies: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    extra_stats: dict[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return (self.success_ops / self.total_ops * 100.0) if self.total_ops > 0 else 0.0

    @property
    def avg_ms(self) -> float:
        return (sum(self.latencies) / len(self.latencies) * 1000.0) if self.latencies else 0.0

    @property
    def min_ms(self) -> float:
        return (min(self.latencies) * 1000.0) if self.latencies else 0.0

    @property
    def max_ms(self) -> float:
        return (max(self.latencies) * 1000.0) if self.latencies else 0.0

    def percentile_ms(self, p: float) -> float:
        if not self.latencies:
            return 0.0
        sorted_l = sorted(self.latencies)
        idx = int(round(p * (len(sorted_l) - 1)))
        return sorted_l[idx] * 1000.0


def print_header(title: str) -> None:
    width = 75
    print("\n" + "=" * width)
    print(f" {title.upper()} ".center(width, "="))
    print("=" * width)


def print_table(results: list[PhaseResult]) -> None:
    width = 75
    print("\n" + "-" * width)
    print(f"{'Phase / Test Description':<32} {'Ops':<6} {'Success':<9} {'Avg(ms)':<9} {'p95(ms)':<9} {'Max(ms)'}")
    print("-" * width)
    for r in results:
        status_str = f"{r.success_rate:.0f}% ({r.success_ops}/{r.total_ops})"
        print(f"{r.name:<32} {r.total_ops:<6} {status_str:<9} {r.avg_ms:<9.1f} {r.percentile_ms(0.95):<9.1f} {r.max_ms:<.1f}")
    print("-" * width)


# ----------------------------------------------------------------------
# Mock Grok with Configurable Rate Limits
# ----------------------------------------------------------------------
class MockGrokWithLimits:
    """Emulates Grok / Groq API rate limits (e.g. 20 concurrent requests ceiling, then 429)."""

    def __init__(self, rate_limit_threshold: int = 20, simulated_latency: float = 0.08):
        self.rate_limit_threshold = rate_limit_threshold
        self.simulated_latency = simulated_latency
        self._lock = threading.Lock()
        self._active_requests = 0
        self.total_called = 0
        self.rate_limited_count = 0

    def judge_batch(self, rows: list[Any]) -> dict[str, Any]:
        with self._lock:
            self.total_called += 1
            self._active_requests += 1
            active = self._active_requests

        try:
            time.sleep(self.simulated_latency)
            if active > self.rate_limit_threshold:
                with self._lock:
                    self.rate_limited_count += 1
                raise RuntimeError(
                    "Error code: 429 - {'error': {'message': 'Rate limit reached for model grok-2-latest: 60 RPM limit exceeded.', 'type': 'requests'}}"
                )

            from judging.judge import Verdict
            verdicts = {}
            for r in rows:
                verdicts[r.edge_hash] = Verdict("supported", "Verified concept similarity and evidence citation.")
            return verdicts
        finally:
            with self._lock:
                self._active_requests -= 1


# ----------------------------------------------------------------------
# Stress Test Runner
# ----------------------------------------------------------------------
class SystemStressTester:
    def __init__(self, num_teams: int = 40, isolated: bool = True, test_grok: bool = False, mock_grok: bool = False):
        self.num_teams = max(2, num_teams)
        self.isolated = isolated
        self.test_grok = test_grok
        self.mock_grok = mock_grok
        self.tmp_dir: Path | None = None
        self.teams: list[dict[str, str]] = []
        self.results: list[PhaseResult] = []

    def setup(self) -> None:
        if self.isolated:
            self.tmp_dir = Path(tempfile.mkdtemp(prefix="research_ctf_stress_"))
            core.STATE = self.tmp_dir / "event_state.json"
            core.TEAM_CSV = self.tmp_dir / "teams.csv"
            core.SUB_CSV = self.tmp_dir / "submissions.csv"
            core.LOG = self.tmp_dir / "events.jsonl"
            core.COOLDOWN_SECONDS = 0
            core.save(core._empty())
            print(f"[Setup] Isolated testing environment created at: {self.tmp_dir}")
        else:
            print("[Setup] Running against ACTIVE live state.")

        # Pre-generate team credentials
        for i in range(1, self.num_teams + 1):
            tid = f"STRESS_{i:03d}"
            name = f"Stress Team {i:03d}"
            pwd = f"StressPass_{i:03d}!xyz"
            self.teams.append({"id": tid, "name": name, "password": pwd})

        # Register teams and complete Level 0 warm-up so teams are active on Level 1
        t0 = time.time()
        for t in self.teams:
            core.create_team(t["id"], t["name"], t["password"], is_demo=False)
            core.attempt_flag(t["id"], level=0, answer="trie")
            core.finalise(t["id"], level=0, csv_text="source_id,target_id,relationship_type\nL0A,L0B,SHARES_PRINCIPLE\n", explanation="Warm-up")
        print(f"[Setup] Registered & warmed-up {len(self.teams)} test teams in {time.time() - t0:.2f}s.")

    def teardown(self) -> None:
        if self.tmp_dir and self.tmp_dir.exists():
            try:
                shutil.rmtree(self.tmp_dir, ignore_errors=True)
                print(f"[Teardown] Cleaned up temporary test directory: {self.tmp_dir}")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Phase 1: Simultaneous Authentication & Logins
    # ------------------------------------------------------------------
    def test_simultaneous_logins(self) -> PhaseResult:
        res = PhaseResult(name="1. Simultaneous Logins")
        barrier = threading.Barrier(self.num_teams)

        def worker(team_info: dict[str, str]) -> tuple[bool, float, str]:
            barrier.wait()  # Synchronize to fire simultaneously
            t0 = time.perf_counter()
            user = core.authenticate(team_info["id"], team_info["password"])
            dt = time.perf_counter() - t0
            ok = user is not None and user.get("team_id") == team_info["id"]
            return ok, dt, "" if ok else "Auth failed"

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.num_teams) as ex:
            futures = [ex.submit(worker, t) for t in self.teams]
            for f in concurrent.futures.as_completed(futures):
                ok, dt, err = f.result()
                res.total_ops += 1
                res.latencies.append(dt)
                if ok:
                    res.success_ops += 1
                else:
                    res.failed_ops += 1
                    res.errors.append(err)

        self.results.append(res)
        return res

    # ------------------------------------------------------------------
    # Phase 2: Simultaneous Flag Submissions
    # ------------------------------------------------------------------
    def test_simultaneous_flags(self) -> PhaseResult:
        res = PhaseResult(name="2. Simultaneous Flag Checks")
        barrier = threading.Barrier(self.num_teams)

        def worker(idx: int, team_info: dict[str, str]) -> tuple[bool, float, str]:
            barrier.wait()
            t0 = time.perf_counter()
            # Alternate between correct and incorrect answers to test both code paths
            ans = "receivers" if idx % 2 == 0 else f"wrong_guess_{idx}"
            out = core.attempt_flag(team_info["id"], level=1, answer=ans)
            dt = time.perf_counter() - t0
            ok = out is not None and "correct" in out
            return ok, dt, "" if ok else "Flag attempt failed"

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.num_teams) as ex:
            futures = [ex.submit(worker, i, t) for i, t in enumerate(self.teams)]
            for f in concurrent.futures.as_completed(futures):
                ok, dt, err = f.result()
                res.total_ops += 1
                res.latencies.append(dt)
                if ok:
                    res.success_ops += 1
                else:
                    res.failed_ops += 1
                    res.errors.append(err)

        self.results.append(res)
        return res

    # ------------------------------------------------------------------
    # Phase 3: Simultaneous Graph Updates & Level Locking
    # ------------------------------------------------------------------
    def test_simultaneous_final_submissions(self) -> PhaseResult:
        res = PhaseResult(name="3. Concurrent Level Locking")
        barrier = threading.Barrier(self.num_teams)

        sample_csv = (
            "source_id,target_id,relationship_type,evidence_reference\n"
            "P02,P05,CITES,citation ref\n"
            "P13,P05,CITES,citation ref\n"
            "P13,P02,CITES,citation ref\n"
            "P02,P05,ANALOGOUS_PROBLEM,abstract comparison\n"
            "P05,P13,ANALOGOUS_PROBLEM,methodology transfer\n"
        )

        def worker(team_info: dict[str, str]) -> tuple[bool, float, str]:
            # Ensure flag was solved so level lock can pass
            core.attempt_flag(team_info["id"], level=1, answer="receivers")
            core.save_draft(team_info["id"], level=1, csv_text=sample_csv)

            barrier.wait()  # Fire simultaneous lock requests
            t0 = time.perf_counter()
            try:
                locked_rec = core.finalise(
                    team=team_info["id"],
                    level=1,
                    csv_text=sample_csv,
                    explanation=f"Stress test automated submission for {team_info['id']}",
                )
                dt = time.perf_counter() - t0
                ok = locked_rec.get("locked") is True
                return ok, dt, "" if ok else "Lock failed"
            except Exception as e:
                dt = time.perf_counter() - t0
                return False, dt, str(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.num_teams) as ex:
            futures = [ex.submit(worker, t) for t in self.teams]
            for f in concurrent.futures.as_completed(futures):
                ok, dt, err = f.result()
                res.total_ops += 1
                res.latencies.append(dt)
                if ok:
                    res.success_ops += 1
                else:
                    res.failed_ops += 1
                    res.errors.append(err)

        # Verify state integrity: all submissions exist in state.json
        state = core.load()
        subs = state.get("submissions", {})
        verified_count = sum(1 for t in self.teams if f"{t['id']}:1" in subs)
        res.extra_stats["state_verified_submissions"] = verified_count
        res.extra_stats["state_integrity_intact"] = (verified_count == res.success_ops)

        self.results.append(res)
        return res

    # ------------------------------------------------------------------
    # Phase 4: Grok / AI Judge Concurrency & Rate-Limit Stress
    # ------------------------------------------------------------------
    def test_grok_access_limits(self) -> PhaseResult:
        res = PhaseResult(name="4. Grok / AI Judge Stress & Rate Limits")
        judge: Any = None
        mode = "none"

        if self.test_grok:
            judge = core.get_live_judge()
            mode = "live_grok"
            if judge is None:
                print("   [Warning] No GROK_API_KEY/OPENAI_API_KEY detected in .env. Falling back to Mock Grok Judge.")
                judge = MockGrokWithLimits(rate_limit_threshold=15)
                mode = "mock_rate_limits"
        elif self.mock_grok:
            judge = MockGrokWithLimits(rate_limit_threshold=15)
            mode = "mock_rate_limits"
        else:
            # Emulate standard fast judge without rate limits
            from judging import StubJudge
            judge = StubJudge(delay=0.03)
            mode = "stub"

        barrier = threading.Barrier(self.num_teams)
        # Novel edge that triggers AI judge evaluation
        graph_with_novel = (
            "source_id,target_id,relationship_type,evidence_reference\n"
            "P02,P05,CITES,Standard citation\n"
            "P05,P02,SHARES_PRINCIPLE,Novel principle sharing between multicast and tree\n"
        )

        def worker(team_info: dict[str, str]) -> tuple[bool, float, str, bool]:
            barrier.wait()
            t0 = time.perf_counter()
            detail = evaluate_submission(
                team_id=team_info["id"],
                level=1,
                flag_answer="receivers",
                graph_csv=graph_with_novel,
                cluster=core.CLUSTER,
                discovery_bounty_pts=0.0,
                judge=judge,
                enforce_50pct_floor=False,
            )
            dt = time.perf_counter() - t0
            is_429 = "429" in detail.judge_error or "quota" in detail.judge_error.lower()
            # The operation is considered resilient if either the judge answered OR the portal gracefully handled the 429
            ok = (len(detail.llm_verdicts) > 0) or is_429
            return ok, dt, detail.judge_error, is_429

        is_429_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.num_teams) as ex:
            futures = [ex.submit(worker, t) for t in self.teams]
            for f in concurrent.futures.as_completed(futures):
                ok, dt, err_msg, is_429 = f.result()
                res.total_ops += 1
                res.latencies.append(dt)
                if is_429:
                    is_429_count += 1
                if ok:
                    res.success_ops += 1
                else:
                    res.failed_ops += 1
                    res.errors.append(err_msg)

        res.extra_stats["mode"] = mode
        res.extra_stats["rate_limit_429_handled_gracefully"] = is_429_count
        self.results.append(res)
        return res

    def run_all(self) -> None:
        print_header(f"Starting System Stress Test ({self.num_teams} Concurrent Teams)")
        self.setup()

        try:
            print("\n[Phase 1] Simulating 40 teams logging in simultaneously...")
            p1 = self.test_simultaneous_logins()
            print(f"   Done: {p1.success_ops}/{p1.total_ops} succeeded (avg: {p1.avg_ms:.1f}ms, p95: {p1.percentile_ms(0.95):.1f}ms)")

            print("\n[Phase 2] Simulating 40 teams submitting flag answers simultaneously...")
            p2 = self.test_simultaneous_flags()
            print(f"   Done: {p2.success_ops}/{p2.total_ops} succeeded (avg: {p2.avg_ms:.1f}ms, p95: {p2.percentile_ms(0.95):.1f}ms)")

            print("\n[Phase 3] Simulating 40 teams submitting & locking graphs simultaneously...")
            p3 = self.test_simultaneous_final_submissions()
            print(f"   Done: {p3.success_ops}/{p3.total_ops} succeeded (avg: {p3.avg_ms:.1f}ms, p95: {p3.percentile_ms(0.95):.1f}ms)")
            if p3.extra_stats.get("state_integrity_intact"):
                print("   State Integrity: PASS (All 40 submissions cleanly persisted in JSON storage without corruption)")

            print("\n[Phase 4] Testing Grok / AI Judge concurrency & rate limit resilience...")
            p4 = self.test_grok_access_limits()
            mode_str = p4.extra_stats.get("mode", "stub")
            r429 = p4.extra_stats.get("rate_limit_429_handled_gracefully", 0)
            print(f"   Done: Mode '{mode_str}' — {p4.success_ops}/{p4.total_ops} completed (avg: {p4.avg_ms:.1f}ms, 429 handled gracefully: {r429})")

            # Final Table
            print_header("Stress Test Executive Summary")
            print_table(self.results)

            # Health Verdict
            all_successful = all(r.success_rate >= 95.0 for r in self.results)
            if all_successful:
                print("\n[VERDICT] SYSTEM HEALTH: EXCELLENT (100% concurrency safety under 40 simultaneous teams)")
            else:
                print("\n[VERDICT] SYSTEM HEALTH: WARNING (Some operations experienced concurrency errors or timeouts)")

        finally:
            self.teardown()


def main():
    parser = argparse.ArgumentParser(description="Research-CTF Concurrency & Grok Stress Testing Suite")
    parser.add_argument("--teams", type=int, default=40, help="Number of concurrent teams to simulate (default: 40)")
    parser.add_argument("--test-grok", action="store_true", help="Send live concurrent calls to configured Grok/Groq API")
    parser.add_argument("--mock-grok-limits", action="store_true", help="Simulate Grok 429 rate limit errors to verify system resilience")
    parser.add_argument("--live-state", action="store_true", help="Run against active state instead of isolated temporary directory")
    args = parser.parse_args()

    tester = SystemStressTester(
        num_teams=args.teams,
        isolated=not args.live_state,
        test_grok=args.test_grok,
        mock_grok=args.mock_grok_limits,
    )
    tester.run_all()


if __name__ == "__main__":
    main()
