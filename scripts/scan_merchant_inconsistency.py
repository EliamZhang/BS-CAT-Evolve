# -*- coding: utf-8 -*-
"""Build non-P0 merchant keyword/category inconsistency candidates for round 4b.

The script only ranks candidate groups and attaches complete sample texts. It
does not decide which side is correct; the AI review does that on the output.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import pandas as pd

MERCHANT_CATEGORIES = {
    "Dining Out", "Retail", "Groceries", "Health", "Automotive",
    "Entertainment", "Home Improvement", "Travel", "Information",
    "Personal Care", "Transport", "Education", "Gyms and other memberships",
    "Pet Care", "Donations", "Utilities", "Telecommunications",
    "Department Stores", "Insurance", "Subscription TV",
}

SAMPLE_FIELDS = [
    ("text", "text"),
    ("transaction_id", "transaction_id"),
    ("application_id", "application_id"),
    ("transaction_date", "transaction_date"),
    ("amount", "amount"),
    ("abs_amount", "abs_amount"),
    ("dr_cr", "dr_cr"),
    ("counterparty", "counterparty"),
]


def load_cache(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_pickle(path)


def label(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).replace("", "(空)")


def sample_records(group: pd.DataFrame) -> list[dict]:
    out = []
    for _, row in group.iterrows():
        rec = {}
        for source, target in SAMPLE_FIELDS:
            value = row.get(source, "")
            if source in ("amount", "abs_amount"):
                try:
                    value = round(float(value), 2)
                except (TypeError, ValueError):
                    value = 0.0
            rec[target] = "" if value is None else str(value)
        out.append(rec)
    return out


def top_share(counts: pd.DataFrame, keys: list[str], name: str) -> pd.DataFrame:
    if counts.empty:
        return pd.DataFrame(columns=keys + [name, f"{name}_share"])
    ordered = counts.sort_values(["n"], ascending=False)
    first = ordered.groupby(keys, dropna=False, sort=False).head(1)
    totals = counts.groupby(keys, dropna=False, sort=False)["n"].sum().reset_index(name="_total")
    first = first.merge(totals, on=keys, how="left")
    first[f"{name}_share"] = (first["n"] / first["_total"]).round(4)
    return first[keys + [name, f"{name}_share"]]


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rank non-P0 merchant keyword/category inconsistency candidates."
    )
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--exclude-keywords", type=Path, default=None)
    parser.add_argument("--top-pairs", type=int, default=100)
    parser.add_argument("--top-keywords", type=int, default=100)
    parser.add_argument("--top-unmatched", type=int, default=100)
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    cache = args.cache.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_cache(cache)
    required = [
        "head_kw", "head_merchant", "head_cat", "finv_Category",
        "illion_Category", "text", "text_clean_channel",
        "application_id", "transaction_id", "amount", "abs_amount",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SystemExit(f"missing cache columns: {missing}")

    df["_kw"] = df["head_kw"].fillna("").astype(str)
    df["_merchant"] = df["head_merchant"].fillna("").astype(str)
    df["_head_cat"] = label(df["head_cat"])
    df["_finv"] = label(df["finv_Category"])
    df["_illion"] = label(df["illion_Category"])
    df["_text_key"] = df["text_clean_channel"].fillna("").astype(str)
    df["_amount"] = pd.to_numeric(df["abs_amount"], errors="coerce").fillna(0.0)
    df["_tx"] = df["transaction_id"].fillna("").astype(str)
    df["_app"] = df["application_id"].fillna("").astype(str)

    known = set()
    if args.exclude_keywords is not None:
        known = set(json.loads(args.exclude_keywords.read_text(encoding="utf-8")))

    # Rows where the HEAD KB matched a non-P0 merchant keyword and the final
    # BSCAT category differs from illion. Known change-list keywords are removed.
    base = df[
        (df["_kw"] != "")
        & df["_head_cat"].isin(MERCHANT_CATEGORIES)
        & (~df["_kw"].isin(known))
        & (df["_finv"] != df["_illion"])
    ].copy()
    excluded_known_rows = int(
        (
            (df["_kw"] != "")
            & df["_head_cat"].isin(MERCHANT_CATEGORIES)
            & df["_kw"].isin(known)
            & (df["_finv"] != df["_illion"])
        ).sum()
    )

    # 1) Keyword + BSCAT vs illion category pairs.
    pair_base = base[base["_finv"].isin(MERCHANT_CATEGORIES)].copy()
    pair_keys = ["_kw", "_merchant", "_head_cat", "_finv", "_illion"]
    pair_metrics = pair_base.groupby(pair_keys, dropna=False, sort=False).agg(
        rows=("_tx", "size"),
        applications=("_app", "nunique"),
        amount=("_amount", "sum"),
        distinct_texts=("_text_key", "nunique"),
    ).reset_index()
    pair_metrics["over_threshold"] = (
        (pair_metrics["rows"] >= 100)
        | (pair_metrics["applications"] >= 10)
        | (pair_metrics["amount"] >= 100_000)
    )
    pair_metrics = pair_metrics.sort_values(
        ["rows", "amount"], ascending=False
    ).reset_index(drop=True)
    top_pairs = pair_metrics.head(args.top_pairs).copy()

    top_pair_keys = top_pairs[pair_keys].drop_duplicates()
    pair_samples_source = pair_base.merge(top_pair_keys, on=pair_keys, how="inner")
    sort_cols = [c for c in ("transaction_date", "transaction_id") if c in pair_samples_source.columns]
    if sort_cols:
        pair_samples_source = pair_samples_source.sort_values(sort_cols, kind="stable")
    pair_samples_source = pair_samples_source.groupby(pair_keys, dropna=False, sort=False).head(3)
    pair_samples = {}
    for key, group in pair_samples_source.groupby(pair_keys, dropna=False, sort=False):
        pair_samples[key] = sample_records(group)

    pair_records = []
    for i, (_, row) in enumerate(top_pairs.iterrows(), start=1):
        key = tuple(row[c] for c in pair_keys)
        samples = pair_samples.get(key, [])
        pair_records.append({
            "rank": i,
            "head_kw": row["_kw"],
            "head_merchant": row["_merchant"],
            "head_cat": row["_head_cat"],
            "bscat": row["_finv"],
            "illion": row["_illion"],
            "rows": int(row["rows"]),
            "applications": int(row["applications"]),
            "amount": round(float(row["amount"]), 2),
            "distinct_texts": int(row["distinct_texts"]),
            "over_threshold": "是" if row["over_threshold"] else "否",
            "samples": samples,
        })

    write_csv(
        out_dir / "merchant_pairs_top.csv",
        [
            {
                **{k: v for k, v in rec.items() if k != "samples"},
                "sample_texts": " || ".join(s["text"] for s in rec["samples"]),
            }
            for rec in pair_records
        ],
        [
            "rank", "head_kw", "head_merchant", "head_cat", "bscat", "illion",
            "rows", "applications", "amount", "distinct_texts",
            "over_threshold", "sample_texts",
        ],
    )
    (out_dir / "merchant_pairs_top.json").write_text(
        json.dumps({
            "cache": str(cache),
            "known_keywords_excluded": sorted(known),
            "pairs": pair_records,
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    # 2) Keyword-level summary: how concentrated is each keyword's illion and
    # final-BSCAT category distribution?
    kw_keys = ["_kw", "_merchant", "_head_cat"]
    kw_metrics = base.groupby(kw_keys, dropna=False, sort=False).agg(
        rows=("_tx", "size"),
        applications=("_app", "nunique"),
        amount=("_amount", "sum"),
        distinct_texts=("_text_key", "nunique"),
        illion_categories=("_illion", "nunique"),
        bscat_categories=("_finv", "nunique"),
    ).reset_index()
    kw_metrics["over_threshold"] = (
        (kw_metrics["rows"] >= 100)
        | (kw_metrics["applications"] >= 10)
        | (kw_metrics["amount"] >= 100_000)
    )
    kw_metrics = kw_metrics.sort_values(
        ["rows", "amount"], ascending=False
    ).reset_index(drop=True)
    top_kw = kw_metrics.head(args.top_keywords).copy()
    top_kw_keys = top_kw[kw_keys].drop_duplicates()

    illion_counts = base.groupby(kw_keys + ["_illion"], dropna=False, sort=False).size().reset_index(name="n")
    illion_counts = illion_counts.merge(top_kw_keys, on=kw_keys, how="inner")
    illion_top = top_share(illion_counts, kw_keys, "_illion")
    bscat_counts = base.groupby(kw_keys + ["_finv"], dropna=False, sort=False).size().reset_index(name="n")
    bscat_counts = bscat_counts.merge(top_kw_keys, on=kw_keys, how="inner")
    bscat_top = top_share(bscat_counts, kw_keys, "_finv")

    kw_samples_source = base.merge(top_kw_keys, on=kw_keys, how="inner")
    if sort_cols:
        kw_samples_source = kw_samples_source.sort_values(sort_cols, kind="stable")
    kw_samples_source = kw_samples_source.groupby(kw_keys, dropna=False, sort=False).head(3)
    kw_samples = {}
    for key, group in kw_samples_source.groupby(kw_keys, dropna=False, sort=False):
        kw_samples[key] = sample_records(group)

    kw_records = []
    for i, (_, row) in enumerate(top_kw.iterrows(), start=1):
        key = tuple(row[c] for c in kw_keys)
        it = illion_top
        bt = bscat_top
        it_row = it[(it["_kw"] == row["_kw"]) & (it["_merchant"] == row["_merchant"]) & (it["_head_cat"] == row["_head_cat"])]
        bt_row = bt[(bt["_kw"] == row["_kw"]) & (bt["_merchant"] == row["_merchant"]) & (bt["_head_cat"] == row["_head_cat"])]
        kw_records.append({
            "rank": i,
            "head_kw": row["_kw"],
            "head_merchant": row["_merchant"],
            "head_cat": row["_head_cat"],
            "rows": int(row["rows"]),
            "applications": int(row["applications"]),
            "amount": round(float(row["amount"]), 2),
            "distinct_texts": int(row["distinct_texts"]),
            "illion_categories": int(row["illion_categories"]),
            "top_illion": "" if it_row.empty else it_row.iloc[0]["_illion"],
            "top_illion_share": 0.0 if it_row.empty else round(float(it_row.iloc[0]["_illion_share"]), 4),
            "bscat_categories": int(row["bscat_categories"]),
            "top_bscat": "" if bt_row.empty else bt_row.iloc[0]["_finv"],
            "over_threshold": "是" if row["over_threshold"] else "否",
            "samples": kw_samples.get(key, []),
        })

    write_csv(
        out_dir / "merchant_keywords_top.csv",
        [
            {
                **{k: v for k, v in rec.items() if k != "samples"},
                "sample_texts": " || ".join(s["text"] for s in rec["samples"]),
            }
            for rec in kw_records
        ],
        [
            "rank", "head_kw", "head_merchant", "head_cat", "rows",
            "applications", "amount", "distinct_texts", "illion_categories",
            "top_illion", "top_illion_share", "bscat_categories", "top_bscat",
            "over_threshold", "sample_texts",
        ],
    )
    (out_dir / "merchant_keywords_top.json").write_text(
        json.dumps({
            "cache": str(cache),
            "known_keywords_excluded": sorted(known),
            "keywords": kw_records,
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    # 3) Unmatched merchant texts: illion is a merchant category but the HEAD
    # KB did not match. These are potential missing keywords/aliases.
    miss = df[
        (df["_kw"] == "")
        & df["_illion"].isin(MERCHANT_CATEGORIES)
        & (df["_finv"] != df["_illion"])
        & ((df["_finv"].isin(MERCHANT_CATEGORIES)) | (df["_finv"] == "(空)"))
    ].copy()
    miss_keys = ["_text_key", "_finv", "_illion"]
    miss_metrics = miss.groupby(miss_keys, dropna=False, sort=False).agg(
        rows=("_tx", "size"),
        applications=("_app", "nunique"),
        amount=("_amount", "sum"),
    ).reset_index()
    miss_metrics["over_threshold"] = (
        (miss_metrics["rows"] >= 100)
        | (miss_metrics["applications"] >= 10)
        | (miss_metrics["amount"] >= 100_000)
    )
    miss_metrics = miss_metrics.sort_values(
        ["rows", "amount"], ascending=False
    ).reset_index(drop=True)
    top_miss = miss_metrics.head(args.top_unmatched).copy()
    top_miss_keys = top_miss[miss_keys].drop_duplicates()
    miss_samples_source = miss.merge(top_miss_keys, on=miss_keys, how="inner")
    if sort_cols:
        miss_samples_source = miss_samples_source.sort_values(sort_cols, kind="stable")
    miss_samples_source = miss_samples_source.groupby(miss_keys, dropna=False, sort=False).head(3)
    miss_samples = {}
    for key, group in miss_samples_source.groupby(miss_keys, dropna=False, sort=False):
        miss_samples[key] = sample_records(group)

    miss_records = []
    for i, (_, row) in enumerate(top_miss.iterrows(), start=1):
        key = tuple(row[c] for c in miss_keys)
        miss_records.append({
            "rank": i,
            "text_clean": row["_text_key"],
            "bscat": row["_finv"],
            "illion": row["_illion"],
            "rows": int(row["rows"]),
            "applications": int(row["applications"]),
            "amount": round(float(row["amount"]), 2),
            "over_threshold": "是" if row["over_threshold"] else "否",
            "samples": miss_samples.get(key, []),
        })

    write_csv(
        out_dir / "unmatched_merchant_texts_top.csv",
        [
            {
                **{k: v for k, v in rec.items() if k != "samples"},
                "sample_texts": " || ".join(s["text"] for s in rec["samples"]),
            }
            for rec in miss_records
        ],
        [
            "rank", "text_clean", "bscat", "illion", "rows",
            "applications", "amount", "over_threshold", "sample_texts",
        ],
    )
    (out_dir / "unmatched_merchant_texts_top.json").write_text(
        json.dumps({
            "cache": str(cache),
            "texts": miss_records,
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    # 4) Category-level summary.
    cat_metrics = base.groupby("_head_cat", dropna=False, sort=False).agg(
        rows=("_tx", "size"),
        applications=("_app", "nunique"),
        amount=("_amount", "sum"),
    ).reset_index().sort_values(["rows", "amount"], ascending=False)
    cat_kw = base.groupby(["_head_cat", "_kw"], dropna=False, sort=False).size().reset_index(name="n")
    cat_kw = cat_kw.sort_values(["n"], ascending=False).groupby("_head_cat", dropna=False, sort=False).head(5)
    cat_illion = base.groupby(["_head_cat", "_illion"], dropna=False, sort=False).size().reset_index(name="n")
    cat_illion = cat_illion.sort_values(["n"], ascending=False).groupby("_head_cat", dropna=False, sort=False).head(5)
    cat_records = []
    for _, row in cat_metrics.iterrows():
        cat = row["_head_cat"]
        kws = cat_kw[cat_kw["_head_cat"] == cat][["_kw", "n"]].values.tolist()
        ills = cat_illion[cat_illion["_head_cat"] == cat][["_illion", "n"]].values.tolist()
        cat_records.append({
            "category": cat,
            "rows": int(row["rows"]),
            "applications": int(row["applications"]),
            "amount": round(float(row["amount"]), 2),
            "top_keywords": kws,
            "top_illion": ills,
        })
    write_csv(
        out_dir / "category_summary.csv",
        [
            {
                "category": rec["category"],
                "rows": rec["rows"],
                "applications": rec["applications"],
                "amount": f"{rec['amount']:.2f}",
                "top_keywords": "; ".join(f"{k} {n}" for k, n in rec["top_keywords"]),
                "top_illion": "; ".join(f"{k} {n}" for k, n in rec["top_illion"]),
            }
            for rec in cat_records
        ],
        ["category", "rows", "applications", "amount", "top_keywords", "top_illion"],
    )
    (out_dir / "category_summary.json").write_text(
        json.dumps(cat_records, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    stats = {
        "round": "4b_non_p0_merchant",
        "cache": str(cache),
        "total_rows": int(len(df)),
        "merchant_keyword_rows": int(len(base)),
        "excluded_known_keyword_rows": excluded_known_rows,
        "known_keywords_excluded": sorted(known),
        "pair_groups": int(len(pair_metrics)),
        "pair_groups_over_threshold": int(pair_metrics["over_threshold"].sum()),
        "keyword_groups": int(len(kw_metrics)),
        "keyword_groups_over_threshold": int(kw_metrics["over_threshold"].sum()),
        "unmatched_rows": int(len(miss)),
        "unmatched_groups": int(len(miss_metrics)),
        "unmatched_groups_over_threshold": int(miss_metrics["over_threshold"].sum()),
        "merchant_categories": sorted(MERCHANT_CATEGORIES),
    }
    stats_path = cache.parent / "audit_cache_stats.json"
    if stats_path.exists():
        cache_stats = json.loads(stats_path.read_text(encoding="utf-8"))
        stats["dataDate"] = cache_stats.get("dataDate", "")
        stats["model_head"] = cache_stats.get("model_head", "")
        stats["cache_dedup_rows"] = cache_stats.get("dedup_rows", 0)
    (out_dir / "merchant_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
