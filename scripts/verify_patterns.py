import csv
import re
import sys
from collections import Counter

csv.field_size_limit(100_000_000)
sys.stdout.reconfigure(encoding="utf-8")

_CLEAN = re.compile(r"[^A-Z0-9]+")
_SEAM = re.compile(r"(?<=\d)(?=[A-Z])|(?<=[A-Z])(?=\d)")
_EFTPOS = re.compile(r"^EFTPOS\s+DEBIT\s+(?:EFTPOS\s+)?\d{1,2}/\d{1,2}\s+\d{1,2}:\d{1,2}", re.I)
_CHANNEL = re.compile(
    r"^(?:BILL\s*PAY(?:MENT)?\s+|VISA\s+(?:WDL|PURCHASE|DEBIT)\s+(?:PURCHASE\s+)?(?:\d+\w+\s+)?\s*|"
    r"VISA\s+CREDIT\s+\d*\s*|EFTPOS\s+(?:DEBIT|WDL)(?:\s+\d+)?\s+|"
    r"MISCELLANEOUS\s+DEBIT\s+V\d+\s+\d+\s+\d+\s+|DEBIT\s+CARD\s+PURCHASE\s+|EFT\s+Dep\s+)",
    re.I,
)


def clean(t):
    t = str(t).upper()
    t = _CLEAN.sub(" ", t)
    return " ".join(t.split())


def clean_initial(t):
    t = str(t).upper()
    t = _EFTPOS.sub("", t)
    t = _CLEAN.sub(" ", t)
    t = _CHANNEL.sub("", t)
    return " ".join(t.split())


def clean_income(t):
    return re.sub(r"\s+", " ", _SEAM.sub(" ", clean(t))).strip()


ROWS = []
with open("output/clusters_top.csv", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        ROWS.append(r)


def report(name, pattern, kind="regex", cleaner=clean, flags=re.I, flow_contains=None):
    rx = re.compile(pattern, flags) if kind == "regex" else None
    flows = Counter()
    hits = []
    for r in ROWS:
        if flow_contains and flow_contains not in r["差异流向"]:
            continue
        text = cleaner(r["text"].replace("\\n", " "))
        if kind == "regex":
            ok = bool(rx.search(text))
        else:
            # engine keyword semantics: whole-word literal
            kw = pattern.upper()
            ok = re.search(r"(?<![A-Z0-9])" + re.escape(kw) + r"(?![A-Z0-9])", text) is not None
        if ok:
            flows[r["差异流向"]] += int(r["笔数"])
            hits.append((r["差异流向"], int(r["笔数"]), r["text"][:70]))
    print(f"\n## {name}  samples={len(hits)} rows={sum(flows.values())}")
    for flow, n in flows.most_common(8):
        print(f"   {n:>7} {flow}")
    for h in hits[:5]:
        print(f"      e.g. {h[1]:>6} {h[0][:38]:<38} {h[2]}")


if __name__ == "__main__":
    # transfer external additions
    report("EXT fast pymt out", r"^fast pymt out")
    report("EXT commbank name comma", r"\btransfer (to|from) [a-z][a-z .,'-]+ commbank app\b")
    report("EXT sav masked mobile", r"^transfer (to|from) sav x{4}\d+ mobile#\s*x*\d+$")
    report("EXT phone", r"^transfer (to|from) phone$")
    report("EXT shop tfc/tfd", r"^shop tf[cd]$")
    # internal additions
    report("INT transfer from s<ref>", r"^transfer from s\d+(?:\.\d+)? #\d+$")
    report("INT deposit online bump saving", r"^deposit online \d+ tfr bump saving$")
    report("INT internet credit effective", r"^internet transfer credit from \d+ ref no \d+ effective date")
    report("INT mb masked", r"^mb transfer (to|from) x+\d+$")
    report("INT fee free txn", r"^fee free txn (?:from:|transfer to:)")
    # fee
    report("FEE overdraw fee comma", r"^Overdraw\s+Fee\b")
    report("FEE debit excess interest comma", r"^Debit\s+Excess\s+Interest\b")
    report("FEE debit excess int adjusted comma", r"^Debit\s+Excess\s+Int\s+Adjusted[, ]+Value\s+Date:")
    report("FEE catchall FEE FREE", r"^(?!.*(?:BIZ\s+CORE|SCHOOL\s+FEES|BODY\s+CORP|BOXING\s+FEES|DISHONOUR|FEE\s+FREE)).{0,40}?\bfees?\b")
    # income
    report("INC FAST PYMT IN strong", r"\bFAST\s*PYMT\s*IN\b", cleaner=clean_income)
    report("INC M-BANKING behavior excl", r"\bM-?BANKING\b", cleaner=clean_income)
    report("INC FUNDS TFER behavior excl", r"\bFUNDS\s+TFER\b", cleaner=clean_income)
    report("INC COINSPOT behavior excl", r"\bCOINSPOT\b", cleaner=clean_income)
    report("INC REPAYMENT/PAYMENT behavior excl", r"^REPAYMENT/PAYMENT$", cleaner=clean_income)
    # AOC keywords (whole-word literal, credit-only engine)
    report("AOC INTEREST", "INTEREST", kind="literal")
    report("AOC REFUND FROM", "REFUND FROM", kind="literal")
    report("AOC ADJUSTMENT TO ACCOUNT", "ADJUSTMENT TO ACCOUNT", kind="literal")
    # credit card
    report("CC payment thankyou", r"^(?:PAYMENT\s+THANK\s*YOU|PAYMENT-BPAY-THANK\s+YOU)\b")
    # dishonour
    report("DISH Returned Item Credit", "RETURNED ITEM CREDIT", kind="literal")
    # catchall generic
    for kw in ["PHONE", "SHOP", "MOBILE", "GIFT"]:
        report(f"CATCH {kw}", kw, kind="literal", flow_contains="External Transfers → Retail")
    # KB additions
    for kw in ["COMPASS", "NANDOS", "EATCLUB", "WESTWATERS", "LIGHT RIDGE", "YARRABILBA",
               "HARRIS FARM", "FOODWORKS", "CANTALOUPE", "KENILWORTH", "CENTRAL COAST VEND",
               "SOMNATH", "HOLT", "STEAMGAMES", "DUNDLE", "TROPSUNPROD", "BINGOBLITZ",
               "CHEMISTWAREHOUSE", "CHEMIST WAREHOUSE"]:
        report(f"KB ADD {kw}", kw, kind="literal", cleaner=clean_initial)
