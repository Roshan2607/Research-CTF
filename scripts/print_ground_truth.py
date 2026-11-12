import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import event_core as core
from scoring.graph_scorer import GraphScorer

cluster = core.CLUSTER
scorer = GraphScorer.from_answer_key()

print("=" * 60)
print("GROUND TRUTH REFERENCE EDGES PER LEVEL")
print("=" * 60)

for lvl in [0, 1, 2, 3, 4]:
    if lvl == 0:
        print(f"\n--- LEVEL 0 (DEMO) ---")
        print("source_id,target_id,relationship_type,evidence_reference")
        print("L0A,L0B,SHARES_PRINCIPLE,Prefix tree / trie data structure used to store shared beginnings once")
        print("L0A,L0B,USES_METHOD,Prefix-sharing tree method applied to cell lineage storage")
        continue

    released = set(core.released_papers(lvl, cluster))
    ref = sorted([t for t in scorer.reference if t[0] in released and t[1] in released])
    print(f"\n--- LEVEL {lvl} ({len(ref)} edges released so far) ---")
    print("source_id,target_id,relationship_type,evidence_reference")
    for s, t, r in ref:
        print(f"{s},{t},{r},Ground truth reference connection")
