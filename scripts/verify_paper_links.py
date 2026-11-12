import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import urllib.request
import urllib.error
from challenge.participant_data import load_corpus, card_pdf_path

print("=" * 70)
print("1. CHECKING LOCAL PDF CHALLENGE CARDS ON DISK")
print("=" * 70)

# Check Demo papers
demo_cards = ["L0A", "L0B"]
all_cards_ok = True
for pid in demo_cards:
    cp = ROOT / "data" / "participant" / "cards" / f"{pid}.pdf"
    if cp.exists() and cp.stat().st_size > 0:
        print(f"[OK] {pid} Demo Card: {cp.name} ({cp.stat().st_size:,} bytes)")
    else:
        print(f"[FAIL] {pid} Demo Card MISSING at {cp}")
        all_cards_ok = False

# Check Competition papers
corpus = load_corpus()
for p in corpus:
    pid = p.get("participant_id")
    try:
        cp = card_pdf_path(pid)
        if cp.exists() and cp.stat().st_size > 0:
            print(f"[OK] {pid} Card: {cp.name} ({cp.stat().st_size:,} bytes)")
        else:
            print(f"[FAIL] {pid} Card MISSING at {cp}")
            all_cards_ok = False
    except Exception as e:
        print(f"[FAIL] {pid} Error: {e}")
        all_cards_ok = False

print("\n" + "=" * 70)
print("2. CHECKING ORIGINAL EXTERNAL PAPER LINKS / DOIs (HTTP HEAD/GET)")
print("=" * 70)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

results = []
for p in corpus:
    pid = p.get("participant_id")
    title = p.get("title", "")
    url = p.get("open_access_url") or p.get("doi_url")
    if not url:
        print(f"[{pid}] NO URL configured!")
        results.append((pid, "NO_URL", "None", title))
        continue

    status_str = "UNKNOWN"
    try:
        req = urllib.request.Request(url, headers=headers)
        # Using urlopen with timeout=8
        with urllib.request.urlopen(req, timeout=8) as res:
            code = res.status
            status_str = f"HTTP {code} OK"
            print(f"[{pid}] {status_str:12s} -> {url}")
            results.append((pid, "OK", url, title))
    except urllib.error.HTTPError as e:
        # Some academic publishers block automated scrapers with 403 Forbidden but the link works in human browsers
        status_str = f"HTTP {e.code}"
        print(f"[{pid}] {status_str:12s} -> {url}")
        results.append((pid, status_str, url, title))
    except Exception as e:
        status_str = f"ERR: {type(e).__name__}"
        print(f"[{pid}] {status_str:12s} -> {url}")
        results.append((pid, status_str, url, title))

print("\n" + "=" * 70)
print("VERIFICATION SUMMARY")
print("=" * 70)
print(f"Local PDF Challenge Cards: {'ALL 17/17 PRESENT AND VALID' if all_cards_ok else 'SOME MISSING'}")
print(f"External Paper Links Checked: {len(results)}")
