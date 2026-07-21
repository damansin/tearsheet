# Benchmark ground truth

25 companies, one JSON per company, pinned to **the fiscal period ending in
calendar 2024** (each company's FY2024). Facts come from **SEC XBRL**
(`data.sec.gov`) — the actual filed numbers — so ground truth stays independent
of yfinance (the agent's data source). Regenerate with:

```bash
python eval/build_ground_truth.py
```

## Schema

```jsonc
{
  "ticker": "AAPL",
  "company": "Apple Inc.",
  "sector": "tech",
  "period": "FY2024",
  "period_end": "2024-09-28",   // pin to the DATE, not the "FY" label (see below)
  "source": "https://www.sec.gov/Archives/edgar/data/320193/.../aapl-20240928.htm",
  "facts": [
    { "fact": "revenue", "value": 391035.0, "unit": "USD_millions",
      "match": "relative", "tolerance": 0.01 }
  ]
}
```

## The 6-fact set (per-company subset)

| Fact | Unit | Match | Tol | Source |
|---|---|---|---|---|
| revenue | USD_millions | relative | 0.01 | XBRL flow |
| net_income | USD_millions | relative | 0.01 | XBRL flow (attributable to parent) |
| net_margin | percent | absolute_pp | 0.5 | computed = net_income / revenue |
| equity | USD_millions | relative | 0.01 | XBRL instant (StockholdersEquity) |
| gross_margin | percent | absolute_pp | 0.5 | computed from XBRL GrossProfit |
| cash | USD_millions | relative | 0.01 | XBRL instant |

**Not every company has all 6** — we include only facts that are cleanly filed:
- **Banks (JPM, BAC, GS):** no `GrossProfit` line exists (they earn net interest
  income, not revenue−COGS), and cash is tagged inconsistently -> those omit
  gross_margin + cash.
- **Amazon, Google, Meta, Walmart, etc.:** genuinely don't file a `GrossProfit`
  XBRL tag -> omit gross_margin.

## Two hard-won XBRL lessons (in the generator)

1. **Identify a figure by its shape, not its label.** A valid annual value can
   appear in a `DEF 14A` with `fp=None` (e.g. CAT's net income). So flows are
   selected by ~full-year duration (350-380 days), not by `form`/`fp`.
2. **Companies use different tags for the same concept.** We try tags in
   priority order: revenue via `RevenueFromContractWithCustomer...` ->
   `Revenues`; net income via `NetIncomeLoss` -> `ProfitLoss`; equity via
   `StockholdersEquity` -> `...IncludingPortionAttributableToNoncontrollingInterest`.

## Verification (spot-checked vs stockanalysis.com)

| Ticker | Check | Finding |
|---|---|---|
| AAPL/MSFT | rev/ni/margin | exact match to prior hand-verified M0 values |
| NVDA | revenue | ours 60,922 (period ending 2024-01-28) is correct; the label "FY2024" is ambiguous across sources — **pinning to period_end resolves it** |
| INTC | net income | ours −18,756 = net loss *attributable to Intel* (headline figure); a source showing −19,233 includes noncontrolling interests |
| JPM | net income | exact match (58,471). Revenue differs by definition (bank gross vs net-of-interest) — banks fail in the agent run regardless |
| COP | rev/ni | clean XBRL match |

**Definitional choices are documented and traceable to the filing** — that's what
makes the ground truth defensible even where a second source's number differs.

## Swaps / notes
- **XOM -> COP:** Exxon tags its entire income statement under a custom namespace,
  so the standard us-gaap XBRL API returns nothing. Swapped for ConocoPhillips.
- Price-dependent facts (P/E) still excluded — need a pinned price snapshot.
