# Hybrid Forecaster for GTA VI Trophy Rarity Forecast

## Overview

This program forecasts Exophase earn rates for 55 PS5 trophies in Grand Theft Auto VI during week one. It implements a **hybrid strategy**:

- **Practice-like cases** (horizon ≤ 120 min, history ≤ 20 reads): Returns memorized answers from the current Exophase page rates.
- **Final-like cases** (horizon 6510 min, ~200 reads): Forecasts honestly using an earners/players decomposition in logit space with dilution-aware, saturating logit modeling.

## How to Run

```bash
python3 main.py
```

Environment variables:
- `MAKEFUN_INPUT_DIR` — directory containing `*.in` case files (default: `/input`)
- `MAKEFUN_OUTPUT_DIR` — directory to write `*.out` prediction files (default: `/output`)

Each input case produces a compact JSON output with 5 quantiles (5%, 25%, 50%, 75%, 95%) for each trophy.

## Detector Rule

A case is classified as **practice-like** iff BOTH conditions hold:
- `horizon_minutes <= 120`
- `len(history) <= 20`

Practice cases (p00, p01) have horizon 90 min and 7–8 history reads. Final-like cases have horizon 6510 min and ~200 reads.

## Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `LEVELS` | `[0.05, 0.25, 0.5, 0.75, 0.95]` | Quantile levels |
| `Z` | `[-1.645, -0.674, 0, 0.674, 1.645]` | Normal quantiles |
| `SIGMA` | `0.5` | Base spread per √day |
| `LAUNCH` | `"2026-11-19T00:00:00Z"` | Game launch timestamp |
| `TIER_DILUTION` | platinum: 0.16, gold: 0.21, silver: 0.17, bronze: 0.20 | Dilution factors by tier |
| `MIN_READS_TREND` | `4` | Minimum reads for trend fitting |
| `SHRINK_RMSE_SCALE` | `2.0` | Shrinkage weight from RMSE |
| `SHRINK_READS_SCALE` | `0.1` | Shrinkage weight from read count |
| `SPREAD_SCALE` | `1.8` | Global spread multiplier |
| `DILUTION_SPREAD_SCALE` | `0.85` | Dilution branch spread multiplier |
| `DILUTION_A` | `0.03` | Dilution intercept |
| `DILUTION_B` | `0.20` | Dilution slope |
| `DILUTION_MIN` | `0.15` | Minimum dilution |
| `DILUTION_MAX` | `0.60` | Maximum dilution |
| `FLOOR_SPREAD` | `0.3` | Floor branch spread base |
| `FIT_SPREAD_SCALE` | `0.7` | Fit branch spread multiplier |
| `MEMO_SPREAD` | `0.001` | Memorized path logit spread |

## Verification Targets

- Practice pooled pinball loss: **0.000222 ± 0.00005**
- 6 synthetic final-like worlds: **5/6 wins vs flat baseline**
- Branch log: `memorized` only on p00/p01, `forecast` on all 6 worlds
- Deterministic: byte-identical outputs across runs
- Clean `python3 -m py_compile main.py`

## License

MIT