import csv
import json
import re
import sys
from collections import Counter

_digits = re.compile(r"\d")
_non_alnum = re.compile(r"[^A-Z0-9#]+")
_ws = re.compile(r"\s+")


def norm_text(value):
    value = value.upper()
    value = _digits.sub("#", value)
    value = _non_alnum.sub(" ", value)
    return _ws.sub(" ", value).strip()


def norm_cp(value):
    value = value.strip().upper()
    return "" if value in ("-", "") else value


def split_flow(value):
    left, sep, right = value.partition("→")
    if not sep:
        return None
    return left.strip(), right.strip()


def flow_ends(value):
    parts = split_flow(value)
    return set(parts) if parts else set()


def stream_pass1(src, scope):
    with open(src, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        need = [
            "差异流向", "amount", "text", "counterparty", "third_party", "dr_cr",
            "illion_Category", "finv_Category", "排查类型", "transaction_date",
            "transaction_id", "application_id",
        ]
        missing = [n for n in need if n not in idx]
        if missing:
            raise SystemExit(f"missing columns: {missing}")
        i_flow, i_amt, i_text, i_cp = (
            idx["差异流向"], idx["amount"], idx["text"], idx["counterparty"]
        )
        i_tp, i_dr, i_ill, i_finv = (
            idx["third_party"], idx["dr_cr"], idx["illion_Category"], idx["finv_Category"]
        )
        i_type, i_date, i_tx, i_app = (
            idx["排查类型"], idx["transaction_date"], idx["transaction_id"], idx["application_id"]
        )

        total = zero = no_flow = outside = 0
        flows = Counter()
        clusters = {}
        for row in reader:
            total += 1
            amt = row[i_amt].strip()
            if not amt:
                zero += 1
                continue
            try:
                if float(amt) == 0:
                    zero += 1
                    continue
            except ValueError:
                zero += 1
                continue
            flow = split_flow(row[i_flow])
            if flow is None:
                no_flow += 1
                continue
            left, right = flow
            if left not in scope and right not in scope:
                outside += 1
                continue
            flow_name = row[i_flow]
            flows[flow_name] += 1
            cp = norm_cp(row[i_cp])
            tx = norm_text(row[i_text])
            key = (flow_name, cp, tx)
            entry = clusters.get(key)
            if entry is None:
                clusters[key] = [
                    1, row[i_date], row[i_amt], row[i_dr], row[i_text], row[i_tp],
                    row[i_cp], row[i_ill], row[i_finv], row[i_type], row[i_tx], row[i_app],
                ]
            else:
                entry[0] += 1
                if row[i_date] < entry[1]:
                    entry[1:] = [
                        row[i_date], row[i_amt], row[i_dr], row[i_text], row[i_tp],
                        row[i_cp], row[i_ill], row[i_finv], row[i_type], row[i_tx],
                        row[i_app],
                    ]
    return {
        "header": header, "total": total, "zero": zero, "no_flow": no_flow,
        "outside": outside, "flows": flows, "clusters": clusters,
    }


def stream_pass2(src, wanted):
    app_sets = {key: set() for key in wanted}
    with open(src, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        i_flow, i_cp, i_text = idx["差异流向"], idx["counterparty"], idx["text"]
        i_app, i_amt = idx["application_id"], idx["amount"]
        for row in reader:
            amt = row[i_amt].strip()
            if not amt:
                continue
            try:
                if float(amt) == 0:
                    continue
            except ValueError:
                continue
            key = (row[i_flow], norm_cp(row[i_cp]), norm_text(row[i_text]))
            s = app_sets.get(key)
            if s is not None:
                s.add(row[i_app])
    return {k: len(v) for k, v in app_sets.items()}


def main(src, scope_json, out_dir):
    scope_cfg = json.load(open(scope_json, encoding="utf-8"))
    scope = set(scope_cfg["scope"])
    p1 = stream_pass1(src, scope)
    flows, clusters = p1["flows"], p1["clusters"]

    scope_rows = sum(flows.values())
    ranked = flows.most_common()
    covered, acc = [], 0
    for name, rows in ranked:
        covered.append(name)
        acc += rows
        if acc >= scope_rows * 0.9:
            break
    covered_set = set(covered)

    p0 = scope_cfg.get("P0", [])
    p0_coverage, p0_backfilled = {}, []
    for cat in p0:
        own = [(name, rows) for name, rows in ranked if cat in flow_ends(name)]
        cat_rows = sum(rows for _, rows in own)
        if not cat_rows:
            p0_coverage[cat] = {"rows": 0, "covered_rows": 0, "ratio": 1.0}
            continue
        cat_covered = sum(rows for name, rows in own if name in covered_set)
        for name, rows in own:
            if cat_covered >= cat_rows * 0.9:
                break
            if name not in covered_set:
                covered.append(name)
                covered_set.add(name)
                cat_covered += rows
                p0_backfilled.append(name)
        p0_coverage[cat] = {
            "rows": cat_rows,
            "covered_rows": cat_covered,
            "ratio": cat_covered / cat_rows,
        }
    covered_rows = sum(rows for name, rows in ranked if name in covered_set)

    flow_clusters = {}
    for (flow, _, _), e in clusters.items():
        flow_clusters.setdefault(flow, []).append(e[0])
    for flow in flow_clusters:
        flow_clusters[flow].sort(reverse=True)

    top_keys = []
    flow_info = []
    for name, rows in ranked:
        counts = flow_clusters.get(name, [])
        top = counts[:10]
        top_rows = sum(top)
        info = {
            "flow": name,
            "rows": rows,
            "clusters": len(counts),
            "covered": name in covered_set,
            "top10_rows": top_rows,
            "top10_clusters": len(top),
            "top10_ratio": top_rows / rows if rows else 0,
            "long_tail": (top_rows / rows if rows else 0) < 0.5,
        }
        flow_info.append(info)
        if name in covered_set:
            keys = [k for k in clusters if k[0] == name]
            keys.sort(key=lambda k: -clusters[k][0])
            top_keys.extend(keys[:10])

    apps = stream_pass2(src, set(top_keys))

    with open(f"{out_dir}/flow_summary.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["差异流向", "笔数", "聚类数", "是否已判定", "Top10笔数", "Top10覆盖率", "长尾"])
        for info in flow_info:
            w.writerow([
                info["flow"], info["rows"], info["clusters"],
                "Y" if info["covered"] else "N", info["top10_rows"],
                f"{info['top10_ratio']:.4f}", "Y" if info["long_tail"] else "N",
            ])

    with open(f"{out_dir}/clusters_top.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "差异流向", "笔数", "app数", "transaction_date", "amount", "dr_cr",
            "text", "third_party", "counterparty", "illion_Category", "finv_Category",
            "排查类型", "transaction_id", "application_id", "text标准化",
            "counterparty标准化",
        ])
        for key in top_keys:
            flow, cp_norm, text_norm = key
            e = clusters[key]
            w.writerow([
                flow, e[0], apps.get(key, 0), e[1], e[2], e[3], e[4], e[5], e[6],
                e[7], e[8], e[9], e[10], e[11], text_norm, cp_norm,
            ])

    uncovered_rows = scope_rows - covered_rows
    uncovered_flows = [i for i in flow_info if not i["covered"]]
    covered_flow_info = [i for i in flow_info if i["covered"]]
    tail_rows = sum(i["rows"] - i["top10_rows"] for i in covered_flow_info)
    tail_clusters = sum(i["clusters"] - i["top10_clusters"] for i in covered_flow_info)
    long_tail = [i["flow"] for i in covered_flow_info if i["long_tail"]]
    stats = {
        "detail_file": src.split("/")[-1].split("\\")[-1],
        "scope_categories": len(scope),
        "total_rows": p1["total"],
        "zero_amount_rows": p1["zero"],
        "no_flow_rows": p1["no_flow"],
        "outside_scope_rows": p1["outside"],
        "scope_rows": scope_rows,
        "flows_total": len(flow_info),
        "flows_covered": len(covered),
        "covered_rows": covered_rows,
        "covered_ratio": covered_rows / scope_rows if scope_rows else 0,
        "uncovered_flows": len(uncovered_flows),
        "uncovered_rows": uncovered_rows,
        "tail_rows_in_covered_flows": tail_rows,
        "tail_clusters_in_covered_flows": tail_clusters,
        "long_tail_flows": long_tail,
        "covered_flow_names": covered,
        "p0_coverage": p0_coverage,
        "p0_backfilled_flows": p0_backfilled,
    }
    json.dump(stats, open(f"{out_dir}/run_stats.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("\ntop flows:")
    for info in flow_info[:30]:
        print(f"{info['rows']:>9} clusters={info['clusters']:>6} "
              f"top10={info['top10_ratio']:.2f} {'C' if info['covered'] else '-'} {info['flow']}")
    print("\nP0 coverage:")
    for cat in p0:
        c = p0_coverage[cat]
        print(f"  {cat:<24} {c['covered_rows']:>9,}/{c['rows']:>9,} {c['ratio']:.1%}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
