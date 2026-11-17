import json
import sys

MONITOR_P0 = [
    "Wages", "Centrelink", "All Other Credits", "SACC Loans", "Non SACC Loans",
    "Unknown Loans", "Credit Card Repayments", "Debt Collection",
    "Debt Consolidation", "Overdrawn",
]
MUST_REVIEW = MONITOR_P0 + ["Dishonours", "Gambling", "Rent"]


def load_data(path):
    s = open(path, encoding="utf-8").read()
    i = s.index("const DATA")
    j = s.index("{", i)
    data, _ = json.JSONDecoder().raw_decode(s, j)
    return data


def pick(cats, key, reverse=False):
    items = [c for c in cats if c.get(key) is not None]
    items.sort(key=lambda c: c["name"])
    items.sort(key=lambda c: c[key], reverse=reverse)
    return [c["name"] for c in items[:5]]


def main(src, out):
    data = load_data(src)
    cats = data["categories"]
    monitor_p0 = {c["name"] for c in cats if c.get("level") == "P0"}
    missing = [n for n in MONITOR_P0 if n not in monitor_p0]
    extra = sorted(monitor_p0 - set(MONITOR_P0))
    if missing or extra:
        print(f"WARN monitor P0 mismatch missing={missing} extra={extra}")

    non_p0 = [c for c in cats if c.get("name") not in MUST_REVIEW]
    g1 = pick(non_p0, "coverage_gap", reverse=False)
    g2 = pick(non_p0, "diff_count", reverse=True)
    g3 = pick(non_p0, "iou_rate", reverse=False)
    selected = []
    for name in MUST_REVIEW + g1 + g2 + g3:
        if name not in selected:
            selected.append(name)

    result = {
        "monitor": src.split("/")[-1].split("\\")[-1],
        "dataDate": data.get("dataDate"),
        "generatedAt": data.get("generatedAt"),
        "P0": MONITOR_P0,
        "must_review": MUST_REVIEW,
        "non_p0_groups": {
            "coverage_gap_lowest": g1,
            "diff_count_highest": g2,
            "iou_rate_lowest": g3,
        },
        "scope": selected,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
