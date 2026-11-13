import csv
import json
import re
import sys

csv.field_size_limit(100_000_000)
sys.stdout.reconfigure(encoding="utf-8")

import ahocorasick

RULES = "output/rules_main"

# --- initial engine cleaning ---
EFTPOS_TS = re.compile(r"^EFTPOS\s+DEBIT\s+(?:EFTPOS\s+)?\d{1,2}/\d{1,2}\s+\d{1,2}:\d{1,2}", re.IGNORECASE)
CHANNEL = re.compile(
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

STOPWORDS = set("""CARD CARDS VISA MASTERCARD AMEX EFTPOS ATM PAYWAVE PAYPASS CONTACTLESS CHIP
BILL BPAY OSKO PAYID PAYTO NPP DIRECT DEBIT CREDIT AUTOPAY RECURRING
PAYMENT PAYMENTS PYMT PYMNT PURCHASE PURCHASES TRANSFER TRANSFERS XFER WITHDRAWAL WITHDRAW
DEPOSIT DEPOSITS REFUND REVERSAL REVERSED REBATE ADJUSTMENT CHARGE CHARGES TRANSACTION TRANS
SETTLEMENT PENDING CLEARED AUTHORISATION AUTHORIZATION FEE FEES INTEREST OVERDRAWN OVERDRAFT
SURCHARGE ONLINE INTERNET MOBILE BANKING BRANCH COUNTER TELLER PHONE AUS AUD AUSTRALIA AUSTRALIAN
INTERNATIONAL OVERSEAS FOREIGN CONVERSION VALUE DATE REFERENCE RECEIPT INVOICE ORDER NUMBER
MISCELLANEOUS SUNDRY GENERAL OTHER PAYEE MERCHANT STORE RETAIL ACCOUNT FUNDS CASH MONEY
LIMITED GROUP HOLDINGS COMPANY CORPORATION ENTERPRISES SERVICES""".split())


def clean_text(text):
    s = text.upper()
    s = EFTPOS_TS.sub("", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = CHANNEL.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def build_kb():
    a = ahocorasick.Automaton()
    seen = {}
    with open(f"{RULES}/initial_engine_merchant_kb.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("category") or "") == "Financial Institutions":
                continue
            kws = (row.get("keywords") or "").split("|")[:50]
            for kw in kws:
                kw = kw.strip()
                if not kw or kw in STOPWORDS:
                    continue
                seen[kw] = (row.get("merchant_name", "").strip(), (row.get("category") or "").strip())
    for kw, val in seen.items():
        a.add_word(kw, (kw, len(kw), val[0], val[1]))
    a.make_automaton()
    return a


def kb_match(a, text_clean):
    best = None
    n = len(text_clean)
    for end_pos, (kw, kw_len, merchant, cat) in a.iter(text_clean):
        pos = end_pos - kw_len + 1
        if pos < 0 or text_clean[pos:pos + kw_len] != kw:
            pos = text_clean.find(kw)
        if pos > 0 and text_clean[pos - 1] != " ":
            continue
        end = pos + kw_len
        if end < n and text_clean[end] != " ":
            continue
        if best is None or kw_len > best[1]:
            best = (kw, kw_len, merchant, cat)
    return best


def load_catchall():
    rules = []
    with open(f"{RULES}/catch_all_engine_resources_catch_all_rules.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                conf = float(row.get("confidence") or 0.5)
            except ValueError:
                conf = 0.5
            rules.append((row.get("rule_name", ""), row.get("category", ""), row.get("pattern", ""),
                          (row.get("match_type") or "keyword").lower(), conf))
    rules.sort(key=lambda r: -r[4])
    return rules


def catchall_match(rules, text_clean):
    for name, cat, kw, mt, conf in rules:
        if mt == "keyword":
            pos = text_clean.find(kw)
            while pos != -1:
                end = pos + len(kw)
                if (pos == 0 or text_clean[pos - 1] == " ") and (end == len(text_clean) or text_clean[end] == " "):
                    return (name, cat, kw, conf)
                pos = text_clean.find(kw, pos + 1)
        else:
            try:
                if re.search(kw, text_clean):
                    return (name, cat, kw, conf)
            except re.error:
                pass
    return None


def main():
    a = build_kb()
    catch_rules = load_catchall()
    rows = []
    with open("output/clusters_top.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            text = row["text"].replace("\\n", " ")
            ct = clean_text(text)
            kb = kb_match(a, ct)
            ca = catchall_match(catch_rules, ct)
            rows.append({
                "flow": row["差异流向"], "rows": int(row["笔数"]), "text": row["text"][:70],
                "illion": row["illion_Category"], "finv": row["finv_Category"],
                "kb": f"{kb[3]}|{kb[2]}|{kb[0]}" if kb else "",
                "catchall": f"{ca[1]}|{ca[0]}|{ca[2]}" if ca else "",
            })
    with open("output/replay_main.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(f'{r["rows"]:>7} {r["flow"][:42]:<42} ill={r["illion"][:18]:<18} finv={r["finv"][:18]:<18} '
              f'kb={r["kb"][:55]:<55} ca={r["catchall"][:40]}')
        print(f'        {r["text"]}')


if __name__ == "__main__":
    main()
