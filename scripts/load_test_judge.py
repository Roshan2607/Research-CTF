"""Simulate N teams submitting at once and report judge latency.

    python scripts/load_test_judge.py --teams 35 --edges 6            # stub judge (no API calls)
    ANTHROPIC_API_KEY=... python scripts/load_test_judge.py --live   # real model, costs tokens
"""
import argparse, os, sys, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from judging import JudgeStore, JudgeWorker, StubJudge
from judging.llm_judge import AnthropicJudge
from judging.openai_judge import OpenAIJudge
from judging.chatgpt_judge import ChatGPTJudge


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", type=int, default=35)
    ap.add_argument("--edges", type=int, default=6, help="novel edges per team (some shared, some unique)")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--provider", choices=["chatgpt", "anthropic", "openai"], default="chatgpt")
    ap.add_argument("--workers", type=int, default=6, help="parallel worker threads")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--show-supported", action="store_true")
    a = ap.parse_args()
    store = JudgeStore(os.path.join(tempfile.mkdtemp(), "load.sqlite3"))
    pids = [f"P{i:02d}" for i in range(1, 16)]
    rels = ["SHARES_PRINCIPLE", "ANALOGOUS_PROBLEM", "USES_METHOD"]
    barrier = threading.Barrier(a.teams)

    def team(i):
        es = [(pids[(i + k) % 15], pids[(i + k * 3 + 5) % 15], rels[k % 3], f"team {i} reasoning {k}") for k in range(a.edges)]
        barrier.wait()
        store.enqueue(f"T{i:02d}", 1, "csv", es)

    t0 = time.time()
    ts = [threading.Thread(target=team, args=(i,)) for i in range(a.teams)]
    [t.start() for t in ts]; [t.join() for t in ts]
    print(f"enqueued {sum(store.counts().values())} unique edges in {time.time() - t0:.2f}s: {store.counts()}")

    cls = {"chatgpt": ChatGPTJudge, "openai": OpenAIJudge, "anthropic": AnthropicJudge}[a.provider]
    judge = cls(samples=a.samples) if a.live else StubJudge(delay=1.5)
    workers = [JudgeWorker(store, judge, batch_size=a.batch) for _ in range(a.workers)]
    t1 = time.time()
    ths = [threading.Thread(target=w.drain) for w in workers]
    [t.start() for t in ths]; [t.join() for t in ths]
    if a.show_supported:
        for r in store._conn().execute("SELECT e.source_id,e.target_id,e.rel_type,e.evidence,j.reason FROM edges e JOIN judgments j USING(edge_hash) WHERE e.status='supported' LIMIT 6"):
            print("SUPPORTED:", tuple(r)[:4], "|", r[4][:160])
    print(f"judged in {time.time() - t1:.1f}s (budget 30s): {store.counts()}")


if __name__ == "__main__":
    main()
