"""Several back-to-back 35-team bursts through the shipped worker pool (28 workers, batch 5).

    python3 scripts/sustained_load.py --bursts 4 --gap 20      # live: spends ChatGPT plan usage
"""
import argparse, os, random, sys, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import event_core as core
from judging import JudgeStore, JudgeWorker
from judging.chatgpt_judge import ChatGPTJudge
from judging.llm_judge import paper_text

ap = argparse.ArgumentParser(); ap.add_argument("--bursts", type=int, default=4); ap.add_argument("--gap", type=float, default=20)
ap.add_argument("--teams", type=int, default=35); ap.add_argument("--per", type=int, default=6); ap.add_argument("--workers", type=int, default=28)
a = ap.parse_args()
sc = core._main_scorer(); rel = set(core.released_papers(4, core.CLUSTER))
pool = sorted(t for t, c in sc.classes.items() if c in ("ordinary", "neutral") and t[0] in rel and t[1] in rel)
q = lambda p: " ".join(paper_text(p).split()[10:22])
judge = ChatGPTJudge(); judge._resolve_model()
errors = []
orig = judge.judge_batch
def counted(batch):
    try:
        return orig(batch)
    except Exception as e:  # noqa: BLE001
        errors.append(f"{type(e).__name__}: {str(e)[:70]}"); raise
judge.judge_batch = counted
print(f"model {judge.model}; {a.bursts} bursts x {a.teams} teams x {a.per} edges; {a.workers} workers; gap {a.gap}s")
allmax = []
for b in range(a.bursts):
    rnd = random.Random(b); edges = pool[:]; rnd.shuffle(edges)
    store = JudgeStore(os.path.join(tempfile.mkdtemp(), "s.sqlite3"))
    gate = threading.Barrier(a.teams)
    def team(i):
        mine = edges[i * a.per:(i + 1) * a.per]; gate.wait()
        store.enqueue(f"T{i:02d}", 1, "csv", [(s, t, r, f'{s} says "{q(s)}"') for s, t, r in mine])
    th = [threading.Thread(target=team, args=(i,)) for i in range(a.teams)]; t0 = time.time(); [x.start() for x in th]; [x.join() for x in th]
    ws = [JudgeWorker(store, judge, batch_size=5) for _ in range(a.workers)]
    th = [threading.Thread(target=w.drain) for w in ws]; [x.start() for x in th]; [x.join() for x in th]
    rows = store._conn().execute("SELECT s.created_at sub, MAX(j.created_at) fin FROM submissions s JOIN submission_edges se ON se.submission_id=s.id JOIN judgments j ON j.edge_hash=se.edge_hash GROUP BY s.id").fetchall()
    lat = sorted(r["fin"] - r["sub"] for r in rows); counts = store.counts()
    allmax.append(lat[-1])
    print(f"burst {b+1}: teams verdict-complete {len(lat)}/{a.teams} | p50 {lat[len(lat)//2]:.1f}s p90 {lat[int(len(lat)*.9)-1]:.1f}s max {lat[-1]:.1f}s | within 30s {sum(x<=30 for x in lat)}/{len(lat)} | pending/deferred {counts.get('pending',0)+counts.get('deferred',0)} | errors so far {len(errors)}")
    if b < a.bursts - 1: time.sleep(a.gap)
print("worst team across all bursts: %.1fs" % max(allmax)); print("distinct errors:", sorted(set(errors)) or "none")
