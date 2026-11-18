import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

_digits = re.compile(r"\d")
_non_alnum = re.compile(r"[^A-Z0-9#]+")
_ws = re.compile(r"\s+")

FIXED_RISK_CATEGORIES = [
    "Credit Card Repayments", "Dishonours", "Gambling", "Rent",
    "SACC Loans", "Non SACC Loans", "Unknown Loans",
    "Debt Collection", "Debt Consolidation", "Overdrawn",
    "External Transfers", "Internal Transfer",
]
HIGH_RISK_KEYWORDS = [
    "CREDIT CARD", "LOAN", "DIRECT DEBIT", "TRANSFER", "DISHONOUR", "RENT",
    "SPORTSBET", "LADBROKES", "TATTS", "POINTSBET", "BET365", "BETFAIR",
    "TAB", "CASINO", "POKER", "LOTTO",
]


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


def amount_status(value):
    value = value.strip()
    if not value:
        return "blank"
    try:
        amount = float(value)
    except ValueError:
        return "invalid"
    if not math.isfinite(amount):
        return "invalid"
    return "zero" if amount == 0 else "valid"


def keyword_pattern(keyword):
    if keyword == "TAB":
        return re.compile(r"(?<![A-Z0-9])TAB(?![A-Z0-9])")
    if keyword in ("LOAN", "RENT"):
        return re.compile(rf"(?<![A-Z0-9]){keyword}")
    if keyword == "TRANSFER":
        return re.compile(r"TRANSFER|(?<![A-Z0-9])TFR(?![A-Z0-9])")
    if keyword == "CREDIT CARD":
        return re.compile(r"CREDIT ?CARD")
    if keyword == "DIRECT DEBIT":
        return re.compile(r"DIRECT ?DEBIT")
    return re.compile(re.escape(keyword))


KEYWORD_PATTERNS = {kw: keyword_pattern(kw) for kw in HIGH_RISK_KEYWORDS}


def keyword_hit(keyword, text_norm, cp_norm):
    pattern = KEYWORD_PATTERNS[keyword]
    return bool(pattern.search(text_norm) or pattern.search(cp_norm))


def stream_rows(header, rows, scope, fixed, sample_date=None):
    idx = {name: i for i, name in enumerate(header)}
    need = [
        "差异流向", "amount", "text", "counterparty", "third_party", "dr_cr",
        "illion_Category", "finv_Category", "排查类型", "transaction_date",
        "transaction_id", "application_id", "sample_datetime",
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
    tracked = scope | fixed

    total = other_dates = period_rows = no_flow = outside = 0
    excluded_amounts = Counter()
    dates = Counter()
    flows = Counter()
    clusters = {}
    app_stats = {}
    for row in rows:
        row = ["" if v is None else str(v) for v in row]
        total += 1
        date = row[idx["sample_datetime"]].strip()
        dates[date] += 1
        if sample_date is not None and date != sample_date:
            other_dates += 1
            continue
        period_rows += 1
        status = amount_status(row[i_amt])
        if status != "valid":
            excluded_amounts[status] += 1
            continue
        flow = split_flow(row[i_flow])
        if flow is None:
            no_flow += 1
            continue
        left, right = flow
        app = row[i_app].strip()
        txid = row[i_tx].strip()
        if app:
            rec = app_stats.get(app)
            if rec is None:
                rec = app_stats[app] = {"tx": {}, "sample": None}
            tx_key = txid or f"row{total}"
            if tx_key not in rec["tx"]:
                rec["tx"][tx_key] = abs(float(row[i_amt]))
                if rec["sample"] is None or (row[i_date], txid) < rec["sample"][:2]:
                    rec["sample"] = (row[i_date], txid, row[i_text], row[i_amt])
        flow_name = row[i_flow]
        if left in scope or right in scope:
            flows[flow_name] += 1
        else:
            outside += 1
        if left not in tracked and right not in tracked:
            continue
        cp = norm_cp(row[i_cp])
        tx = norm_text(row[i_text])
        key = (flow_name, row[i_dr].strip().lower(), cp, tx)
        entry = clusters.get(key)
        if entry is None:
            clusters[key] = [
                1, row[i_date], row[i_amt], row[i_dr], row[i_text], row[i_tp],
                row[i_cp], row[i_ill], row[i_finv], row[i_type], row[i_tx],
                row[i_app], {app} if app else set(),
            ]
        else:
            entry[0] += 1
            if app:
                entry[12].add(app)
            if (row[i_date], txid) < (entry[1], entry[10].strip()):
                entry[1:12] = [
                    row[i_date], row[i_amt], row[i_dr], row[i_text], row[i_tp],
                    row[i_cp], row[i_ill], row[i_finv], row[i_type], row[i_tx],
                    row[i_app],
                ]
    return {
        "header": header, "total": total, "other_dates": other_dates,
        "period_rows": period_rows, "dates": dates,
        "excluded_amounts": excluded_amounts, "no_flow": no_flow,
        "outside": outside, "flows": flows, "clusters": clusters,
        "app_stats": app_stats,
    }


def stream_pass1(src, scope, fixed, sample_date):
    with open(src, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        return stream_rows(header, reader, scope, fixed, sample_date)


def load_cache_rows(path):
    import pandas as pd

    path = Path(path)
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_pickle(path)
    return list(df.columns), df.itertuples(index=False, name=None)


def load_app_set(path):
    if not path:
        return None
    apps = set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            app = (row.get("application_id") or "").strip()
            if app:
                apps.add(app)
    return apps


def cluster_rank(clusters):
    return lambda k: (-clusters[k][0], k[3], k[2], k[1])


def cluster_rank_global(clusters):
    return lambda k: (-clusters[k][0], k[0], k[3], k[2], k[1])


def main(src, scope_json, out_dir, income=None, liability=None, evolve=None, cache=None):
    scope_cfg = json.load(open(scope_json, encoding="utf-8"))
    scope = set(scope_cfg["scope"])
    fixed = set(FIXED_RISK_CATEGORIES)
    if cache:
        header, rows = load_cache_rows(cache)
        p1 = stream_rows(header, rows, scope, fixed, sample_date=None)
        nonempty = [d for d in p1["dates"] if d]
        sample_date = f"{min(nonempty)}~{max(nonempty)}" if nonempty else ""
    else:
        sample_date = str(scope_cfg.get("dataDate", "")).strip()
        if not sample_date:
            raise SystemExit("scope.json missing dataDate; rebuild it with parse_monitor.py")
        p1 = stream_pass1(src, scope, fixed, sample_date)
    if not p1["period_rows"]:
        raise SystemExit(f"no detail rows for dataDate={sample_date}; available={sorted(p1['dates'])}")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    flows, clusters = p1["flows"], p1["clusters"]
    rank = cluster_rank(clusters)
    rank_global = cluster_rank_global(clusters)

    scope_rows = sum(flows.values())
    ranked = sorted(flows.items(), key=lambda kv: (-kv[1], kv[0]))
    covered, acc = [], 0
    for name, rows in ranked:
        covered.append(name)
        acc += rows
        if acc >= scope_rows * 0.9:
            break
    covered_set = set(covered)

    must_review = scope_cfg.get("must_review") or scope_cfg.get("P0", [])
    must_review_coverage, must_review_backfilled = {}, []
    for cat in must_review:
        own = [(name, rows) for name, rows in ranked if cat in flow_ends(name)]
        cat_rows = sum(rows for _, rows in own)
        if not cat_rows:
            continue
        cat_covered = sum(rows for name, rows in own if name in covered_set)
        for name, rows in own:
            if cat_covered >= cat_rows * 0.9:
                break
            if name not in covered_set:
                covered.append(name)
                covered_set.add(name)
                cat_covered += rows
                must_review_backfilled.append(name)
    # Later backfills can also cover earlier categories. Report the final union.
    for cat in must_review:
        own = [(name, rows) for name, rows in ranked if cat in flow_ends(name)]
        cat_rows = sum(rows for _, rows in own)
        cat_covered = sum(rows for name, rows in own if name in covered_set)
        must_review_coverage[cat] = {
            "rows": cat_rows, "covered_rows": cat_covered,
            "ratio": cat_covered / cat_rows if cat_rows else None,
        }
    covered_rows = sum(rows for name, rows in ranked if name in covered_set)

    flow_keys = {}
    for key in clusters:
        flow_keys.setdefault(key[0], []).append(key)
    for keys in flow_keys.values():
        keys.sort(key=rank)

    top_keys = []
    flow_info = []
    for name, rows in ranked:
        keys = flow_keys.get(name, [])
        top = keys[:10]
        top_rows = sum(clusters[k][0] for k in top)
        info = {
            "flow": name,
            "rows": rows,
            "clusters": len(keys),
            "covered": name in covered_set,
            "top10_rows": top_rows,
            "top10_clusters": len(top),
            "top10_ratio": top_rows / rows if rows else 0,
            "long_tail": (top_rows / rows if rows else 0) < 0.5,
        }
        flow_info.append(info)
        if name in covered_set:
            top_keys.extend(top)

    with open(f"{out_dir}/flow_summary.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["差异流向", "笔数", "聚类数", "是否入选", "Top10笔数", "Top10覆盖率", "长尾"])
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
            flow, _, cp_norm, text_norm = key
            e = clusters[key]
            w.writerow([
                flow, e[0], len(e[12]), e[1], e[2], e[3], e[4], e[5], e[6],
                e[7], e[8], e[9], e[10], e[11], text_norm, cp_norm,
            ])

    round2_flows = [i for i in flow_info if not i["covered"]][:15]
    round2_rows = sum(i["rows"] for i in round2_flows)
    round2_met = round2_rows >= 100
    round2_keys = []
    if round2_met:
        for info in round2_flows:
            round2_keys.extend(flow_keys.get(info["flow"], [])[:10])
        with open(f"{out_dir}/round2_candidates.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "差异流向", "流向笔数", "笔数", "app数", "dr_cr", "text",
                "counterparty", "third_party", "transaction_date", "amount",
                "illion_Category", "finv_Category", "排查类型", "transaction_id",
                "application_id", "text标准化", "counterparty标准化",
            ])
            for info in round2_flows:
                for key in flow_keys.get(info["flow"], [])[:10]:
                    e = clusters[key]
                    w.writerow([
                        key[0], info["rows"], e[0], len(e[12]), e[3], e[4], e[6],
                        e[5], e[1], e[2], e[7], e[8], e[9], e[10], e[11],
                        key[3], key[2],
                    ])

    long_tail_keys = []
    for name in covered:
        long_tail_keys.extend(flow_keys.get(name, [])[10:])
    long_tail_keys.sort(key=rank_global)
    hit_labels = {}

    def add_hit(key, label):
        labels = hit_labels.setdefault(key, [])
        if label not in labels:
            labels.append(label)

    for key in long_tail_keys[:100]:
        add_hit(key, "长尾")
    keyword_stats = {}
    for keyword in HIGH_RISK_KEYWORDS:
        matched = [k for k in long_tail_keys if keyword_hit(keyword, k[3], k[2])]
        selected = matched[:10]
        keyword_stats[keyword] = {"matched": len(matched), "selected": len(selected)}
        for key in selected:
            add_hit(key, keyword)

    round4_stats = {}
    round4_examples = []
    for cat in FIXED_RISK_CATEGORIES:
        cat_keys = [k for k in clusters if cat in flow_ends(k[0])]
        cat_keys.sort(key=rank_global)
        selected = cat_keys[:10]
        round4_stats[cat] = {
            "rows": sum(clusters[k][0] for k in cat_keys),
            "clusters": len(cat_keys),
            "top10_clusters": len(selected),
            "top10_rows": sum(clusters[k][0] for k in selected),
        }
        for key in selected:
            add_hit(key, cat)
        for key in selected[:3]:
            e = clusters[key]
            round4_examples.append([
                cat, key[0], e[4], e[6], e[10], e[11], e[1], e[2],
            ])

    blind_keys = sorted(hit_labels, key=rank_global)
    with open(f"{out_dir}/blind_spot.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "簇", "笔数", "app数", "差异流向", "样本", "命中入口", "dr_cr",
            "counterparty", "third_party", "transaction_date", "amount",
            "illion_Category", "finv_Category", "排查类型", "transaction_id",
            "application_id", "text标准化", "counterparty标准化",
        ])
        for key in blind_keys:
            e = clusters[key]
            flow, dr, cp_norm, text_norm = key
            w.writerow([
                f"{flow}|{dr}|{cp_norm}|{text_norm}", e[0], len(e[12]), flow,
                e[4], ";".join(hit_labels[key]), e[3], e[6], e[5], e[1], e[2],
                e[7], e[8], e[9], e[10], e[11], text_norm, cp_norm,
            ])

    with open(f"{out_dir}/round4_examples.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "类别", "差异流向", "text", "counterparty", "transaction_id",
            "application_id", "transaction_date", "amount",
        ])
        w.writerows(round4_examples)

    income_apps = load_app_set(income)
    liability_apps = load_app_set(liability)
    app_rank = sorted(p1["app_stats"].items(), key=lambda kv: (-len(kv[1]["tx"]), kv[0]))
    top_count_apps = [app for app, _ in app_rank[:20]]
    amt_rank = sorted(p1["app_stats"].items(),
                      key=lambda kv: (-sum(kv[1]["tx"].values()), kv[0]))
    top_amount_apps = [app for app, _ in amt_rank[:10]]
    missing_liability = []
    if income_apps is not None and liability_apps is not None:
        missing_liability = sorted(
            app for app in p1["app_stats"]
            if app in income_apps and app not in liability_apps
        )

    round3_keys = [k for k in blind_keys
                   if any(lb == "长尾" or lb in KEYWORD_PATTERNS for lb in hit_labels[k])]
    round4_keys = [k for k in blind_keys
                   if any(lb in fixed for lb in hit_labels[k])]
    round_apps = {}
    round_sources = [
        ("第1轮", top_keys), ("第2轮", round2_keys),
        ("第3轮", round3_keys), ("第4轮", round4_keys),
    ]
    for label, keys in round_sources:
        for key in keys:
            for app in clusters[key][12]:
                labels = round_apps.setdefault(app, [])
                if label not in labels:
                    labels.append(label)

    reasons = {}
    for app in top_count_apps:
        reasons.setdefault(app, []).append("差异笔数前20")
    for app in top_amount_apps:
        reasons.setdefault(app, []).append("差异金额前10")
    for app in missing_liability:
        reasons.setdefault(app, []).append("收入有、负债无")
    for app, labels in round_apps.items():
        reasons.setdefault(app, []).extend(labels)
    selected_apps = sorted(reasons, key=lambda a: (-len(p1["app_stats"][a]["tx"]), a))[:50]

    with open(f"{out_dir}/app_context.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "申请", "差异笔数", "差异金额", "有无负债摘要", "候选根因", "样本",
            "入选来源", "有无收入摘要",
        ])
        for app in selected_apps:
            rec = p1["app_stats"][app]
            count = len(rec["tx"])
            amount = sum(rec["tx"].values())
            w.writerow([
                app, count, f"{amount:.2f}",
                "" if liability_apps is None else ("Y" if app in liability_apps else "N"),
                "", rec["sample"][2], ";".join(reasons[app]),
                "" if income_apps is None else ("Y" if app in income_apps else "N"),
            ])

    evolve_rows = 0
    if evolve:
        selected_set = set(selected_apps)
        with open(evolve, encoding="utf-8-sig", newline="") as f, \
                open(f"{out_dir}/app_evolve_context.csv", "w", encoding="utf-8-sig", newline="") as out:
            reader = csv.reader(f)
            header = next(reader)
            idx = {name: i for i, name in enumerate(header)}
            i_app = idx.get("application_id")
            i_tx = idx.get("transaction_id")
            if i_app is None:
                raise SystemExit("evolve file missing application_id")
            w = csv.writer(out)
            w.writerow(header + ["是否差异"])
            for row in reader:
                app = row[i_app].strip()
                if app not in selected_set:
                    continue
                diff = "Y" if i_tx is not None and row[i_tx].strip() in p1["app_stats"][app]["tx"] else "N"
                w.writerow(row + [diff])
                evolve_rows += 1

    uncovered_rows = scope_rows - covered_rows
    uncovered_flows = [i for i in flow_info if not i["covered"]]
    covered_flow_info = [i for i in flow_info if i["covered"]]
    tail_rows = sum(i["rows"] - i["top10_rows"] for i in covered_flow_info)
    tail_clusters = sum(i["clusters"] - i["top10_clusters"] for i in covered_flow_info)
    long_tail = [i["flow"] for i in covered_flow_info if i["long_tail"]]
    stats = {
        "detail_file": "" if cache else src.split("/")[-1].split("\\")[-1],
        "cache_file": str(cache) if cache else "",
        "dataDate": sample_date,
        "scope_file": str(scope_json),
        "scope_categories": len(scope),
        "total_rows": p1["total"],
        "rows_by_date": dict(sorted(p1["dates"].items())),
        "other_date_rows": p1["other_dates"],
        "period_rows": p1["period_rows"],
        "blank_amount_rows": p1["excluded_amounts"]["blank"],
        "zero_amount_rows": p1["excluded_amounts"]["zero"],
        "invalid_amount_rows": p1["excluded_amounts"]["invalid"],
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
        "top_cluster_rows": covered_rows - tail_rows,
        "tail_clusters_in_covered_flows": tail_clusters,
        "long_tail_flows": long_tail,
        "covered_flow_names": covered,
        "must_review_coverage": must_review_coverage,
        "must_review_backfilled_flows": must_review_backfilled,
        "round2": {
            "flows": [{"flow": i["flow"], "rows": i["rows"]} for i in round2_flows],
            "rows": round2_rows,
            "threshold_met": round2_met,
            "candidate_clusters": len(round2_keys),
        },
        "round3": {
            "long_tail_clusters": len(long_tail_keys),
            "top100_clusters": min(100, len(long_tail_keys)),
            "keyword_hits": keyword_stats,
        },
        "round4": round4_stats,
        "blind_spot_clusters": len(blind_keys),
        "round5": {
            "app_total": len(p1["app_stats"]),
            "top_count_apps": len(top_count_apps),
            "top_amount_apps": len(top_amount_apps),
            "income_without_liability_apps": len(missing_liability),
            "cluster_apps": len(round_apps),
            "selected_apps": len(selected_apps),
            "evolve_rows": evolve_rows,
        },
    }
    json.dump(stats, open(f"{out_dir}/run_stats.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("\ntop flows:")
    for info in flow_info[:30]:
        print(f"{info['rows']:>9} clusters={info['clusters']:>6} "
              f"top10={info['top10_ratio']:.2f} {'C' if info['covered'] else '-'} {info['flow']}")
    print("\nmust-review coverage:")
    for cat in must_review:
        c = must_review_coverage[cat]
        ratio = f"{c['ratio']:.1%}" if c['ratio'] is not None else "N/A (no difference rows)"
        print(f"  {cat:<24} {c['covered_rows']:>9,}/{c['rows']:>9,} {ratio}")
    print(f"\ncandidates: round2={len(round2_keys)} (threshold_met={round2_met}) "
          f"blind_spot={len(blind_keys)} round5_apps={len(selected_apps)} "
          f"evolve_rows={evolve_rows}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("src")
    parser.add_argument("scope_json")
    parser.add_argument("out_dir")
    parser.add_argument("--income")
    parser.add_argument("--liability")
    parser.add_argument("--evolve")
    parser.add_argument("--cache", action="store_true",
                        help="treat src as an audit cache built with build_audit_cache.py --all-dates")
    args = parser.parse_args()
    main(args.src, args.scope_json, args.out_dir,
         income=args.income, liability=args.liability, evolve=args.evolve,
         cache=args.src if args.cache else None)
