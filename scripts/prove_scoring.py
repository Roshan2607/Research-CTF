"""Check the live level scorer against hand-computed values: weights, level scoping, injection timing.

    python3 scripts/prove_scoring.py     # no API calls; exits non-zero on any mismatch
"""
import csv, io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import event_core as core
from challenge import paths

sc = core._main_scorer(); W = sc.weights
fails = []
def csv_of(edges):
    b = io.StringIO(); w = csv.writer(b, lineterminator="\n"); w.writerow(["source_id","target_id","relationship_type","evidence_reference"])
    for e in edges: w.writerow([*e, "x"])
    return b.getvalue()
def f1(tp, fn, wfp):
    p = tp / (tp + wfp) if tp + wfp else 0; r = tp / (tp + fn) if tp + fn else 0
    return (round(p, 4), round(r, 4), round(2 * p * r / (p + r), 4) if p + r else 0.0)
def check(name, got, want):
    ok = all(abs(g - w) < 1e-3 for g, w in zip(got, want))
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got P/R/F1={got} expected {want}")
    if not ok: fails.append(name)
def score(level, edges):
    r = core.score_level_graph(core.CLUSTER, level, csv_of(edges))
    return (r["weighted_precision"], r["recall"], r["weighted_f1"]), r

print("weights:", W)
for level in (1, 2, 3, 4):
    rel = set(core.released_papers(level, core.CLUSTER))
    ins = lambda c: sorted(t for t, k in sc.classes.items() if k == c and t[0] in rel and t[1] in rel)
    ref, ordn, decoy = ins("reference"), ins("ordinary"), ins("decoy_induced")
    n = len(ref)
    check(f"L{level} all {n} reference edges", score(level, ref)[0], (1, 1, 1))
    check(f"L{level} empty-ish (1 ref edge only)", score(level, ref[:1])[0], f1(1, n - 1, 0))
    check(f"L{level} all ref + 2 ordinary (w={W['ordinary']})", score(level, ref + ordn[:2])[0], f1(n, 0, 2 * W["ordinary"]))
    check(f"L{level} all ref + 2 decoy-induced (w={W['decoy_induced']})", score(level, ref + decoy[:2])[0], f1(n, 0, 2 * W["decoy_induced"]))
    half = ref[: n // 2]
    check(f"L{level} half the ref + 1 ordinary", score(level, half + ordn[:1])[0], f1(len(half), n - len(half), W["ordinary"]))
    # edges that use papers not yet released must be ignored entirely
    later = sorted(t for t, k in sc.classes.items() if k == "reference" and not (t[0] in rel and t[1] in rel))
    if later:
        check(f"L{level} unreleased-paper edges ignored", score(level, ref + later[:3])[0], (1, 1, 1))

# injection edges: weight 3x only once the host card is released
ann = json.load(open(paths.INJECTIONS))["annotations"]
print("\ninjection annotations:", [(a["induced_edge"], a["host_card_participant_id"]) for a in ann])
for a in ann:
    e = tuple(a["induced_edge"]); host = a["host_card_participant_id"]
    lv_host = next(lv for lv in (1, 2, 3, 4) if host in core.released_papers(lv, core.CLUSTER))
    for lv in (1, 2, 3, 4):
        rel = set(core.released_papers(lv, core.CLUSTER))
        if e[0] not in rel or e[1] not in rel: continue
        ref = sorted(t for t, k in sc.classes.items() if k == "reference" and t[0] in rel and t[1] in rel)
        got, r = score(lv, ref + [e])
        released = host in rel
        cls = "injection (3x)" if released else "ordinary/decoy (host card not yet released)"
        exp_w = W["injection_induced"] if released else (W["decoy_induced"] if (e[0] in {d["participant_id"] for d in json.load(open(paths.DECOYS))["decoys"]} or e[1] in {d["participant_id"] for d in json.load(open(paths.DECOYS))["decoys"]}) else W["ordinary"])
        check(f"injection edge {e} at L{lv} (host {host} released={released}) -> {cls}", got, f1(len(ref), 0, exp_w))
print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
