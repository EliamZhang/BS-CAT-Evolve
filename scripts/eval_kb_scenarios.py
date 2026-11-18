# -*- coding: utf-8 -*-
"""Evaluate merchant-KB scenarios against the shared audit cache.

Loads the HEAD KB and each candidate KB once, matches unique cleaned texts,
then joins the result back to transactions to count rows / applications / amount.
This is an initial-engine simulation only; later engines may override it.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_audit_cache import (  # noqa: E402
    build_auto, classify, git_value, load_kw_map, load_stopwords,
)


def load_cache(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_pickle(path)


def ensure_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "text_clean_channel" not in df.columns:
        from build_audit_cache import clean_channel

        df = df.copy()
        df["text_clean_channel"] = df["text"].fillna("").map(clean_channel)
    else:
        df = df.copy()
        df["text_clean_channel"] = df["text_clean_channel"].fillna("").astype(str)
    if "head_kw" in df.columns:
        df["head_kw"] = df["head_kw"].fillna("").astype(str)
    return df


def ensure_head(df: pd.DataFrame, kw_map: dict[str, tuple[str, str]]) -> pd.DataFrame:
    if "head_kw" in df.columns and df["head_kw"].astype(str).str.len().gt(0).any():
        return df
    auto = build_auto(kw_map)
    head_map = {t: classify(t, auto) for t in pd.unique(df["text_clean_channel"])}
    values = [head_map.get(t) for t in df["text_clean_channel"]]
    df = df.copy()
    df["head_kw"] = [v[1] if v else "" for v in values]
    df["head_cat"] = [v[3] if v else "" for v in values]
    df["head_merchant"] = [v[2] if v else "" for v in values]
    return df


def sorted_group(group: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ("transaction_date", "transaction_id") if c in group.columns]
    return group.sort_values(cols, kind="stable") if cols else group


def summarize(group: pd.DataFrame) -> dict:
    return {
        "rows": int(len(group)),
        "applications": int(group["application_id"].nunique()),
        "amount": round(float(group["_audit_amount"].sum()), 2),
    }


def samples(group: pd.DataFrame, limit: int = 3) -> list[dict]:
    out = []
    for _, row in sorted_group(group).head(limit).iterrows():
        out.append({
            "transaction_id": str(row.get("transaction_id", "")),
            "application_id": str(row.get("application_id", "")),
            "amount": round(float(row.get("_audit_amount", 0.0)), 2),
            "text": str(row.get("text", "")),
        })
    return out


def expand_keywords(values) -> list[str]:
    out = []
    for value in values:
        for variant in str(value).split("|")[:50]:
            variant = variant.strip()
            if variant:
                out.append(variant)
    return out


def evaluate(df: pd.DataFrame, kw_map: dict[str, tuple[str, str]], spec: dict) -> dict:
    name = str(spec.get("name", "")).strip()
    if not name:
        raise SystemExit("scenario name missing")
    target = spec.get("target_category")
    if target is None:
        raise SystemExit(f"{name}: target_category missing")
    targets = [target] if isinstance(target, str) else list(target)
    target_set = {str(t) for t in targets}

    scope = expand_keywords(spec.get("scope_keywords") or [])
    if not scope:
        raise SystemExit(f"{name}: scope_keywords missing")
    remove = expand_keywords(spec.get("remove_keywords") or [])
    adds = list(spec.get("add_keywords") or [])

    finv = df["finv_Category"].fillna("").astype(str)
    if "*" in target_set:
        cat_mask = pd.Series(True, index=df.index)
    else:
        cat_mask = finv.isin(target_set)
        if target_set & {"", "(空)"}:
            cat_mask = cat_mask | (finv == "")

    scope_mask = (
        pd.Series(True, index=df.index)
        if "*" in scope
        else df["head_kw"].astype(str).isin(scope)
    )
    subset = df.loc[scope_mask & cat_mask].copy()
    subset["_audit_amount"] = (
        pd.to_numeric(subset["abs_amount"], errors="coerce").fillna(0.0)
        if "abs_amount" in subset.columns
        else pd.to_numeric(subset["amount"], errors="coerce").abs().fillna(0.0)
    )

    remove_set = set(remove)
    cand_map = {k: v for k, v in kw_map.items() if k not in remove_set}
    for add in adds:
        variants = expand_keywords([add.get("keyword", "")])
        if not variants:
            raise SystemExit(f"{name}: empty add_keywords.keyword")
        merchant = str(add.get("merchant", ""))
        category = str(add.get("category", ""))
        for variant in variants:
            cand_map[variant] = (merchant, category)

    auto = build_auto(cand_map)
    text_map = {t: classify(t, auto) for t in pd.unique(subset["text_clean_channel"])}
    values = [text_map.get(t) for t in subset["text_clean_channel"]]
    subset["_cand_kw"] = [v[1] if v else "" for v in values]
    subset["_cand_cat"] = [v[3] if v else "(空)" for v in values]
    subset["_cand_merchant"] = [v[2] if v else "" for v in values]

    new_categories = []
    for category, group in subset.groupby("_cand_cat", sort=False):
        category = str(category) or "(空)"
        new_categories.append({
            "category": category,
            **summarize(group),
            "sample_transactions": samples(group),
        })
    new_categories.sort(key=lambda x: (-x["rows"], x["category"]))

    head_keywords = []
    for keyword, group in subset.groupby("head_kw", sort=False):
        keyword = str(keyword) or "(无命中)"
        head_keywords.append({"keyword": keyword, **summarize(group)})
    head_keywords.sort(key=lambda x: (-x["rows"], x["keyword"]))

    impact = summarize(subset) if len(subset) else {
        "rows": 0, "applications": 0, "amount": 0.0,
    }
    new_match_rows = int((subset["_cand_kw"] != "").sum()) if len(subset) else 0
    return {
        "name": name,
        "target_category": target,
        "scope_keywords": scope,
        "remove_keywords": remove,
        "add_keywords": adds,
        "impact": impact,
        "new_match_rows": new_match_rows,
        "unmatched_rows": impact["rows"] - new_match_rows,
        "new_categories": new_categories,
        "head_keywords": head_keywords,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate merchant-KB scenarios on the audit cache.")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--kb", type=Path, default=None)
    parser.add_argument("--csv", type=Path, default=None)
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    cache = args.cache.resolve()
    model = args.model.resolve()
    kb_path = (args.kb or (model / "initial_engine" / "merchant_kb.csv")).resolve()
    cls_path = model / "initial_engine" / "domain" / "classification.py"
    if not kb_path.exists() or not cls_path.exists():
        raise SystemExit(f"merchant KB or classification.py not found: {kb_path} / {cls_path}")

    df = ensure_text_columns(load_cache(cache))
    stopwords = load_stopwords(cls_path)
    kw_map = load_kw_map(kb_path, stopwords)

    current_head = git_value(model, "rev-parse", "--short", "HEAD")
    stats = {}
    stats_path = cache.parent / "audit_cache_stats.json"
    if stats_path.exists():
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        if stats.get("model_head") and current_head and stats["model_head"] != current_head:
            print(
                f"WARNING: cache built at {stats['model_head']}, current model HEAD "
                f"{current_head}; recomputing HEAD matches",
                file=sys.stderr,
            )
            if "head_kw" in df.columns:
                df["head_kw"] = ""
                df["head_cat"] = ""
                df["head_merchant"] = ""

    df = ensure_head(df, kw_map)

    raw = json.loads(args.scenarios.read_text(encoding="utf-8"))
    specs = raw.get("scenarios", []) if isinstance(raw, dict) else raw
    if not isinstance(specs, list) or not specs:
        raise SystemExit("scenarios file must be a non-empty list or {'scenarios': [...]}")

    results = [evaluate(df, kw_map, spec) for spec in specs]
    payload = {
        "cache": str(cache),
        "model": str(model),
        "model_head": current_head,
        "kb_file": str(kb_path),
        "note": "初始引擎 merchant_kb 独立匹配模拟；后续引擎可能覆盖，最终以端到端复跑为准。",
        "scenarios": results,
    }
    if stats:
        payload["dataDate"] = stats.get("dataDate", "")
        payload["cache_model_head"] = stats.get("model_head", "")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                "scenario", "target_category", "new_category",
                "rows", "applications", "amount",
            ])
            for result in results:
                impact = result["impact"]
                writer.writerow([
                    result["name"], result["target_category"], "(合计)",
                    impact["rows"], impact["applications"], f"{impact['amount']:.2f}",
                ])
                for item in result["new_categories"]:
                    writer.writerow([
                        result["name"], result["target_category"], item["category"],
                        item["rows"], item["applications"], f"{item['amount']:.2f}",
                    ])

    for result in results:
        impact = result["impact"]
        top = ", ".join(
            f"{item['category']} {item['rows']}"
            for item in result["new_categories"][:3]
        )
        print(
            f"{result['name']}: {impact['rows']} / {impact['applications']} / "
            f"{impact['amount']:.2f}; {top}"
        )


if __name__ == "__main__":
    main()
