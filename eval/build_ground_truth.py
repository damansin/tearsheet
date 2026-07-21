"""Generate benchmark ground truth from SEC XBRL (the source of record).

    python eval/build_ground_truth.py

For each company: resolve CIK -> pull each fact from data.sec.gov's XBRL
companyconcept API (trying tags in priority order) -> keep only the FY2024
annual 10-K figure -> compute margins -> write eval/benchmark/<TICKER>.json in
the M0 schema, citing the real 10-K URL.

Why XBRL: it's the actual filed numbers, not a third party's interpretation, so
it stays independent of yfinance (the agent's data source). Messiness handled:
companies tag the same concept differently, and banks lack a gross-profit line.
"""

import json
import time
import urllib.request
from datetime import date
from pathlib import Path

BENCHMARK_DIR = Path(__file__).parent / "benchmark"
UA = {"User-Agent": "Tearsheet research daman@example.com"}
FISCAL_END_YEAR = 2024  # pin to the fiscal period ENDING in calendar 2024

# ticker -> (sector, is_bank). Banks lack GrossProfit and tag cash oddly, so
# they omit gross_margin + cash (see FACTS_FOR below).
COMPANIES = {
    "AAPL": ("tech", False), "MSFT": ("tech", False), "GOOGL": ("tech", False),
    "NVDA": ("tech", False), "AMZN": ("tech", False), "META": ("tech", False),
    "WMT": ("retail", False), "COST": ("retail", False), "HD": ("retail", False),
    "KO": ("consumer", False), "PG": ("consumer", False), "MCD": ("consumer", False),
    "NKE": ("consumer", False), "JNJ": ("healthcare", False), "UNH": ("healthcare", False),
    "PFE": ("healthcare", False), "COP": ("energy", False), "CVX": ("energy", False),
    "CAT": ("industrial", False),
    "JPM": ("financial", True), "BAC": ("financial", True), "GS": ("financial", True),
    "INTC": ("tech", False), "BA": ("industrial", False), "RIVN": ("auto", False),
}

# Concept tags to try, in priority order (first that returns FY2024 data wins).
TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "RevenuesNetOfInterestExpense"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "gross_profit": ["GrossProfit"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
}

# Flows (income-statement figures) span a period; instants (balance-sheet
# figures) are a point in time. We identify them differently — see annual_2024.
FLOW_FACTS = {"revenue", "net_income", "gross_profit"}


def _get(url):
    time.sleep(0.15)  # be polite to SEC (<10 req/s)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def ticker_to_cik() -> dict[str, str]:
    rows = _get("https://www.sec.gov/files/company_tickers.json").values()
    return {r["ticker"]: str(r["cik_str"]).zfill(10) for r in rows}


def annual_2024(cik: str, tag: str, is_flow: bool):
    """(value, period_end) for the FY2024 figure, or None.

    A figure is identified by its shape, NOT its form/period label (those are
    unreliable — a valid annual value can appear in a DEF 14A with fp=None):
      - flows (income statement): a ~full-year duration (350-380 days) ending 2024
      - instants (balance sheet): a point-in-time value from a 10-K ending 2024
    Among matches, prefer the 10-K, then the latest-filed (final/restated) value.
    """
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    try:
        data = _get(url)
    except Exception:
        return None
    best = None
    for u in data.get("units", {}).get("USD", []):
        end = str(u.get("end", ""))
        if not end.startswith(str(FISCAL_END_YEAR)):
            continue
        start = u.get("start")
        if is_flow:
            if not start:
                continue
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days
            if not (350 <= days <= 380):  # full fiscal year only
                continue
        else:
            if start:  # instants have no duration
                continue
            if u.get("form") != "10-K":  # year-end balance, not a 10-Q quarter
                continue
        rank = (u.get("form") == "10-K", u.get("filed", ""))  # prefer 10-K, latest
        if best is None or rank > best[0]:
            best = (rank, u)
    return (best[1]["val"], best[1]["end"]) if best else None


def first_available(cik: str, fact: str):
    is_flow = fact in FLOW_FACTS
    for tag in TAGS[fact]:
        got = annual_2024(cik, tag, is_flow)
        if got:
            return got
    return None


def tenk_url_and_name(cik: str):
    """(10-K document URL, company name) for the FY2024 filing."""
    subs = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    name = subs.get("name", "")
    recent = subs["filings"]["recent"]
    for form, acc, doc, rpt in zip(
        recent["form"], recent["accessionNumber"],
        recent["primaryDocument"], recent["reportDate"],
    ):
        if form == "10-K" and str(rpt).startswith(str(FISCAL_END_YEAR)):
            acc_nodash = acc.replace("-", "")
            cik_int = int(cik)
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"
            return url, name
    return "", name


def facts_for(ticker: str, is_bank: bool, cik: str) -> tuple[list, str]:
    """Build the facts list + period_end for one company."""
    rev = first_available(cik, "revenue")
    ni = first_available(cik, "net_income")
    if not rev or not ni:
        raise RuntimeError(f"{ticker}: missing revenue or net_income")

    period_end = rev[1]
    facts = [
        _money("revenue", rev[0]),
        _money("net_income", ni[0]),
        _pct("net_margin", ni[0] / rev[0] * 100),
    ]

    equity = first_available(cik, "equity")
    if equity:
        facts.append(_money("equity", equity[0]))

    if not is_bank:  # banks: no gross profit line, cash tagged inconsistently
        gp = first_available(cik, "gross_profit")
        if gp:
            facts.append(_pct("gross_margin", gp[0] / rev[0] * 100))
        cash = first_available(cik, "cash")
        if cash:
            facts.append(_money("cash", cash[0]))

    return facts, period_end


def _money(name, raw_dollars):
    return {"fact": name, "value": round(raw_dollars / 1e6, 2),
            "unit": "USD_millions", "match": "relative", "tolerance": 0.01}


def _pct(name, value):
    return {"fact": name, "value": round(value, 2),
            "unit": "percent", "match": "absolute_pp", "tolerance": 0.5}


def main() -> None:
    cik_map = ticker_to_cik()
    for ticker, (sector, is_bank) in COMPANIES.items():
        cik = cik_map.get(ticker)
        if not cik:
            print(f"{ticker}: NO CIK — skipped")
            continue
        try:
            facts, period_end = facts_for(ticker, is_bank, cik)
            source, name = tenk_url_and_name(cik)
            doc = {
                "ticker": ticker, "company": name, "sector": sector,
                "period": f"FY{FISCAL_END_YEAR}", "period_end": period_end,
                "source": source, "facts": facts,
            }
            (BENCHMARK_DIR / f"{ticker}.json").write_text(json.dumps(doc, indent=2) + "\n")
            tags = ", ".join(f["fact"] for f in facts)
            print(f"{ticker:6} {period_end}  {len(facts)} facts: {tags}")
        except Exception as exc:  # noqa: BLE001
            print(f"{ticker:6} FAILED: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
