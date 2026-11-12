"""Integration test for the concurrency stress test suite."""
from scripts.stress_test_system import SystemStressTester


def test_stress_suite_fast_smoke():
    tester = SystemStressTester(num_teams=6, isolated=True, mock_grok=True)
    tester.run_all()
    assert len(tester.results) == 4
    for r in tester.results:
        assert r.success_rate >= 90.0
