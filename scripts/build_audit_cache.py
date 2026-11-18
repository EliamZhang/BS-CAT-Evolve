# -*- coding: utf-8 -*-
"""Build the shared audit cache used by classification rounds.

One streaming pass over the diff detail writes the deduped valid rows with
cleaned text and HEAD initial-engine merchant-KB matches, so later rounds and
rule simulations do not rescan the full 3.3M-row detail. With --all-dates the
cache covers every sample_datetime date and keeps the latest snapshot per
(application_id, transaction_id).
"""
import argparse
import ast
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import ahocorasick
import numpy as np
import pandas as pd

_EFTPOS_TS_RE = re.compile(
    r"^EFTPOS\s+DEBIT\s+(?:EFTPOS\s+)?\d{1,2}/\d{1,2}\s+\d{1,2}:\d{1,2}",
    re.IGNORECASE,
)
_CHANNEL_PREFIX_RE = re.compile(
    r"^(?:"
    r"BILL\s*PAY(?:MENT)?\s+|"
    r"VISA\s+(?:WDL|PURCHASE|DEBIT)\s+(?:PURCHASE\s+)?(?:\d+\w+\s+)?\s*|"
    r"VISA\s+CREDIT\s+\d*\s*|"
    r"EFTPOS\s+(?:DEBIT|WDL)(?:\s+\d+)?\s+|"
    r"MISCELLANEOUS\s+DEBIT\s+V\d+\s+\d+\s+\d+\s+|"
    r"DEBIT\s+CARD\s+PURCHASE\s+|"
    r"EFT\s+Dep\s+"
    r")",
    re.IGNORECASE,
)
_DIGITS_RE = re.compile(r"\d")
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9#]+")
_WS_RE = re.compile(r"\s+")

DETAIL_COLUMNS = [
    "排查类型", "差异流向", "transaction_date", "amount", "dr_cr", "text",
    "third_party", "counterparty", "illion_Category", "finv_Category",
    "user_id", "application_id", "transaction_id", "job_id", "bank_account_id",
    "sample_datetime",
]
REQUIRED_COLUMNS = [
    "差异流向", "transaction_date", "amount", "dr_cr", "text",
    "illion_Category", "finv_Category", "application_id", "transaction_id",
    "sample_datetime",
]


def clean_text(value: object) -> str:
    text = "" if value is None else str(value).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return " ".join(text.split())


def clean_channel(value: object) -> str:
    text = "" if value is None else str(value).upper()
    text = _EFTPOS_TS_RE.sub("", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = _CHANNEL_PREFIX_RE.sub("", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return " ".join(text.split())


def norm_text(value: object) -> str:
    text = "" if value is None else str(value).upper()
    text = _DIGITS_RE.sub("#", text)
    text = _NON_ALNUM_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def norm_cp(value: object) -> str:
    text = "" if value is None else str(value).strip().upper()
    return "" if text in ("-", "") else text


def load_stopwords(cls_path: Path) -> set[str]:
    src = cls_path.read_text(encoding="utf-8")
    m = re.search(r"_STOPWORDS\s*(?::[^=]+)?=\s*frozenset\(", src)
    if not m:
        raise SystemExit(f"_STOPWORDS not found in {cls_path}")
    start = m.end() - 1
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return set(ast.literal_eval(src[start:i + 1]))
    raise SystemExit(f"unbalanced _STOPWORDS in {cls_path}")


def load_kw_map(kb_path: Path, stopwords: set[str]) -> dict[str, tuple[str, str]]:
    kw_map: dict[str, tuple[str, str]] = {}
    chunks = pd.read_csv(
        kb_path,
        usecols=["merchant_name", "keywords", "category"],
        chunksize=100_000,
        encoding="utf-8-sig",
        dtype="string",
    )
    for chunk in chunks:
        chunk = chunk[chunk["keywords"].notna() & (chunk["keywords"].str.strip() != "")]
        chunk = chunk[chunk["category"].fillna("") != "Financial Institutions"]
        if chunk.empty:
            continue
        lists = chunk["keywords"].str.split("|").str[:50]
        ex = chunk[["merchant_name", "category"]].copy()
        ex["_kw"] = lists
        ex = ex.explode("_kw").dropna(subset=["_kw"])
        ex["_kw"] = ex["_kw"].str.strip()
        ex = ex[~ex["_kw"].isin(stopwords)]
        ex["merchant_name"] = ex["merchant_name"].fillna("").str.strip()
        ex["category"] = ex["category"].fillna("").str.strip()
        for kw, merchant, category in zip(
            ex["_kw"].values, ex["merchant_name"].values, ex["category"].values
        ):
            if kw:
                kw_map[kw] = (merchant, category)
    return kw_map


def build_auto(kw_map: dict[str, tuple[str, str]]):
    if not kw_map:
        return None
    auto = ahocorasick.Automaton()
    for kw, (merchant, category) in kw_map.items():
        auto.add_word(kw, (kw, len(kw), merchant, category))
    auto.make_automaton()
    return auto


def classify(text: str, auto):
    if auto is None:
        return None
    n = len(text)
    best = None
    for end_pos, (kw, kw_len, merchant, cat) in auto.iter(text):
        pos = end_pos - kw_len + 1
        if pos < 0 or text[pos:pos + kw_len] != kw:
            pos = end_pos - kw_len
            if pos < 0 or text[pos:pos + kw_len] != kw:
                pos = text.find(kw)
                if pos == -1:
                    continue
        if pos > 0 and text[pos - 1] != " ":
            continue
        end = pos + kw_len
        if end < n:
            nxt = text[end]
            if nxt != " " and not ("0" <= nxt <= "9"):
                continue
        if best is None or kw_len > best[0]:
            best = (kw_len, kw, merchant, cat)
    return best


def read_header(path: Path) -> list[str]:
    csv.field_size_limit(1 << 30)
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return next(csv.reader(fh))


def load_detail(detail: Path, data_date: str | None, chunksize: int):
    header = read_header(detail)
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise SystemExit(f"missing detail columns: {missing}")
    usecols = [c for c in DETAIL_COLUMNS if c in header]

    frames = []
    total_rows = period_rows = valid_rows = 0
    blank = zero = invalid = 0
    rows_by_date: dict[str, int] = {}
    blank_date_rows = 0

    reader = pd.read_csv(
        detail,
        usecols=usecols,
        dtype=str,
        keep_default_na=False,
        na_values=[],
        chunksize=chunksize,
        encoding="utf-8-sig",
    )
    for chunk in reader:
        total_rows += len(chunk)
        if data_date is not None:
            chunk = chunk[chunk["sample_datetime"] == data_date]
            period_rows += len(chunk)
        else:
            counts = chunk["sample_datetime"].value_counts().to_dict()
            for date, n in counts.items():
                rows_by_date[date] = rows_by_date.get(date, 0) + int(n)
            period_rows += len(chunk)
            blank_date_rows += int((chunk["sample_datetime"].str.strip() == "").sum())
        if chunk.empty:
            continue

        raw_amount = chunk["amount"]
        amount = pd.to_numeric(raw_amount, errors="coerce")
        is_blank = raw_amount.str.strip() == ""
        is_invalid = (~is_blank) & (amount.isna() | ~np.isfinite(amount))
        is_zero = (~is_blank) & (~is_invalid) & (amount == 0)
        is_valid = (~is_blank) & (~is_invalid) & (~is_zero)

        blank += int(is_blank.sum())
        invalid += int(is_invalid.sum())
        zero += int(is_zero.sum())
        valid_rows += int(is_valid.sum())

        chunk = chunk.loc[is_valid].copy()
        chunk["amount"] = amount.loc[is_valid].astype(float)
        chunk["abs_amount"] = chunk["amount"].abs()
        frames.append(chunk)

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=usecols)
    return df, {
        "total_rows": total_rows,
        "period_rows": period_rows,
        "blank_date_rows": blank_date_rows,
        "rows_by_date": dict(sorted(rows_by_date.items())),
        "blank_amount_rows": blank,
        "zero_amount_rows": zero,
        "invalid_amount_rows": invalid,
        "valid_amount_rows": valid_rows,
    }


def git_value(model: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(model), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def resolve_format(requested: str) -> str:
    if requested == "pickle":
        return "pickle"
    if requested == "parquet":
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            raise SystemExit("parquet requires pyarrow; install it or use --format pickle")
        return "parquet"
    try:
        import pyarrow  # noqa: F401
        return "parquet"
    except ImportError:
        return "pickle"


def build_cache(detail: Path, scope_path: Path, out_dir: Path, model: Path | None,
                chunksize: int, fmt: str, all_dates: bool = False) -> dict:
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    data_date = str(scope.get("dataDate", "")).strip()
    if not all_dates and not data_date:
        raise SystemExit(f"dataDate missing in {scope_path}")
    fmt = resolve_format(fmt)

    df, counts = load_detail(detail, None if all_dates else data_date, chunksize)

    before_dedup = len(df)
    if before_dedup:
        if all_dates:
            df = df.sort_values("sample_datetime", kind="stable")
            df = df.drop_duplicates(
                subset=["application_id", "transaction_id"], keep="last"
            ).reset_index(drop=True)
        else:
            df = df.drop_duplicates(
                subset=["application_id", "transaction_id"], keep="first"
            ).reset_index(drop=True)
    duplicates_removed = before_dedup - len(df)

    missing_key_rows = 0
    if len(df):
        missing_key_rows = int(
            ((df["application_id"].str.strip() == "") |
             (df["transaction_id"].str.strip() == "")).sum()
        )

    raw = df["text"].fillna("") if len(df) else pd.Series(dtype="object")
    unique_text = pd.unique(raw)
    clean_map = {t: clean_text(t) for t in unique_text}
    channel_map = {t: clean_channel(t) for t in unique_text}
    norm_map = {t: norm_text(t) for t in unique_text}
    df["text_clean"] = raw.map(clean_map) if len(df) else ""
    df["text_clean_channel"] = raw.map(channel_map) if len(df) else ""
    df["text_norm"] = raw.map(norm_map) if len(df) else ""

    raw_cp = df["counterparty"].fillna("") if len(df) else pd.Series(dtype="object")
    cp_map = {t: norm_cp(t) for t in pd.unique(raw_cp)}
    df["counterparty_norm"] = raw_cp.map(cp_map) if len(df) else ""

    head_kw: list[str] = []
    head_cat: list[str] = []
    head_merchant: list[str] = []
    kb_keywords = 0
    kb_file = ""
    model_head = ""
    model_branch = ""
    model_dirty = False

    if model is not None:
        model_head = git_value(model, "rev-parse", "--short", "HEAD")
        model_branch = git_value(model, "rev-parse", "--abbrev-ref", "HEAD")
        model_dirty = bool(git_value(model, "status", "--porcelain"))
        kb_path = model / "initial_engine" / "merchant_kb.csv"
        cls_path = model / "initial_engine" / "domain" / "classification.py"
        if not kb_path.exists() or not cls_path.exists():
            raise SystemExit(f"merchant KB or classification.py not found under {model}")
        stopwords = load_stopwords(cls_path)
        kw_map = load_kw_map(kb_path, stopwords)
        kb_keywords = len(kw_map)
        kb_file = str(kb_path)
        auto = build_auto(kw_map)
        head_map = {
            t: classify(t, auto)
            for t in pd.unique(df["text_clean_channel"])
        } if len(df) else {}
        values = [head_map.get(t) for t in df["text_clean_channel"]]
        head_kw = [v[1] if v else "" for v in values]
        head_cat = [v[3] if v else "" for v in values]
        head_merchant = [v[2] if v else "" for v in values]

    df["head_kw"] = head_kw if head_kw else ""
    df["head_cat"] = head_cat if head_cat else ""
    df["head_merchant"] = head_merchant if head_merchant else ""

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "audit_cache_all" if all_dates else "audit_cache"
    cache_path = out_dir / (f"{stem}.parquet" if fmt == "parquet" else f"{stem}.pkl")
    if fmt == "parquet":
        df.to_parquet(cache_path, index=False)
    else:
        df.to_pickle(cache_path)

    if all_dates:
        dates = [d for d in counts["rows_by_date"] if d]
        data_date = f"{min(dates)}~{max(dates)}" if dates else ""

    head_matched_rows = sum(1 for v in head_kw if v)
    stats = {
        "detail_file": str(detail),
        "dataDate": data_date,
        "all_dates": all_dates,
        "scope_file": str(scope_path),
        "model_path": str(model) if model is not None else "",
        "model_head": model_head,
        "model_branch": model_branch,
        "model_dirty": model_dirty,
        "kb_file": kb_file,
        "kb_keywords": kb_keywords,
        "cache_file": str(cache_path),
        "cache_format": fmt,
        **counts,
        "duplicates_removed": duplicates_removed,
        "dedup_rows": len(df),
        "missing_key_rows": missing_key_rows,
        "unique_texts": int(df["text"].nunique()) if len(df) else 0,
        "unique_texts_clean_channel": int(df["text_clean_channel"].nunique()) if len(df) else 0,
        "head_matched_rows": head_matched_rows,
        "head_unmatched_rows": len(df) - head_matched_rows,
        "finv_category_counts": (
            {str(k): int(v) for k, v in df["finv_Category"].value_counts().items()}
            if len(df) else {}
        ),
        "columns": list(df.columns),
    }
    stats_paths = [out_dir / "audit_cache_stats.json"]
    if all_dates:
        stats_paths.insert(0, out_dir / "audit_cache_all_stats.json")
    payload = json.dumps(stats, ensure_ascii=False, indent=1)
    for stats_path in stats_paths:
        stats_path.write_text(payload, encoding="utf-8")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the shared daily audit cache.")
    parser.add_argument("detail", type=Path)
    parser.add_argument("scope", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--chunksize", type=int, default=200_000)
    parser.add_argument("--format", choices=["auto", "pickle", "parquet"], default="auto")
    parser.add_argument("--all-dates", action="store_true",
                        help="read every sample_datetime date and keep the latest snapshot per transaction")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    stats = build_cache(
        args.detail.resolve(), args.scope.resolve(), args.out_dir.resolve(),
        args.model.resolve() if args.model else None, args.chunksize, args.format,
        all_dates=args.all_dates,
    )
    print(json.dumps({
        "cache_file": stats["cache_file"],
        "cache_format": stats["cache_format"],
        "dataDate": stats["dataDate"],
        "all_dates": stats["all_dates"],
        "rows_by_date": stats["rows_by_date"],
        "period_rows": stats["period_rows"],
        "dedup_rows": stats["dedup_rows"],
        "duplicates_removed": stats["duplicates_removed"],
        "zero_amount_rows": stats["zero_amount_rows"],
        "unique_texts": stats["unique_texts"],
        "head_matched_rows": stats["head_matched_rows"],
        "model_head": stats["model_head"],
        "model_branch": stats["model_branch"],
        "model_dirty": stats["model_dirty"],
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
