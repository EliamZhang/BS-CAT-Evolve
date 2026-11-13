import csv
import sys

csv.field_size_limit(100_000_000)
kb = sys.argv[1]
patterns = [p.upper() for p in sys.argv[2:]]

with open(kb, encoding="utf-8-sig", newline="") as f:
    for lineno, row in enumerate(csv.DictReader(f), start=2):
        keywords = (row.get("keywords") or "").split("|")
        hits = []
        for i, kw in enumerate(keywords):
            ku = kw.strip().upper()
            if any(p in ku for p in patterns):
                hits.append((i, kw.strip()))
        if hits:
            print(f"line={lineno} merchant={row.get('merchant_name')!r} "
                  f"category={row.get('category')!r} variants={len(keywords)}")
            for i, kw in hits[:12]:
                print(f"    [{i}] {kw!r}")
