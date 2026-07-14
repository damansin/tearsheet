# Benchmark ground truth

One JSON file per company. Facts are hand-curated from the company's SEC 10-K
filing (the source of record) — deliberately **not** from yfinance, so the
ground truth stays independent of the data source the agent reads.

## Schema

```jsonc
{
  "ticker": "AAPL",           // the benchmark key
  "company": "Apple Inc.",
  "period": "FY2024",          // facts are PINNED to a filing period, never "latest"
  "period_end": "2024-09-28",  // fiscal year end date
  "source": "https://...",     // the 10-K on SEC EDGAR — every fact traces here
  "facts": [
    {
      "fact": "revenue",        // key the agent's output must provide
      "value": 391035,          // ground-truth value
      "unit": "USD_millions",   // scorer normalizes units before comparing
      "match": "relative",      // how to compare (see below)
      "tolerance": 0.01
    }
  ]
}
```

## Match types

| `match`       | Meaning                                   | Typical use                       |
|---------------|-------------------------------------------|-----------------------------------|
| `relative`    | |agent − truth| / truth ≤ tolerance       | reported figures (revenue, NI); ±1% absorbs rounding, still catches hallucinations |
| `absolute_pp` | |agent − truth| ≤ tolerance (in points)   | percentages (margins); ±0.5pp     |

## Rules

- **Pin, don't drift.** Facts come from a specific filing period so ground truth
  never changes as new quarters land. FY2025 filings existing is irrelevant.
- **No price-dependent facts in M0** (e.g. P/E). They need a pinned price
  snapshot — added in M1 with the full 20–30 company benchmark.
- **Tolerance discipline.** Loose enough to absorb formatting/rounding, tight
  enough that a $36B→$40B misstatement always fails.

## Verification log

| Ticker | Figures cross-checked against | Filing verified via |
|--------|-------------------------------|---------------------|
| AAPL   | stockanalysis.com vs 10-K (rev 391,035 / NI 93,736 / GM 46.21%) | SEC EDGAR submissions API, accession 0000320193-24-000123 |
| MSFT   | stockanalysis.com vs 10-K (rev 245,122 / NI 88,136 / GM 69.76%) | SEC EDGAR submissions API, accession 0000950170-24-087843 |
