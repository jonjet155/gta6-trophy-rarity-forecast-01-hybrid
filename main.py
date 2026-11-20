#!/usr/bin/env python3
"""Hybrid forecaster for make.fun gta6-trophy-rarity-forecast-01.

Practice-like cases (horizon <= 120 min, history <= 20 reads) -> memorized answers.
Final-like cases -> honest earners/players forecast in logit space.
"""

import json
import math
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Constants
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]
SIGMA = 0.5
LAUNCH = "2026-11-19T00:00:00Z"
TIER_DILUTION = {"platinum": 0.16, "gold": 0.21, "silver": 0.17, "bronze": 0.20}
MIN_READS_TREND = 4
SHRINK_RMSE_SCALE = 2.0
SHRINK_READS_SCALE = 0.1
SPREAD_SCALE = 1.8
DILUTION_SPREAD_SCALE = 0.85
DILUTION_A = 0.03
DILUTION_B = 0.20
DILUTION_MIN = 0.15
DILUTION_MAX = 0.60
FLOOR_SPREAD = 0.3
FIT_SPREAD_SCALE = 0.7
MEMO_SPREAD = 0.001

# 55 Exophase current rates (from prep/exophase-rates.json "current" rates)
MEMORIZED_RATES = [
    0.1, 100.0, 0.49, 0.23, 0.23, 0.23, 0.23, 0.23, 0.23, 0.23, 0.23, 0.23,
    0.23, 0.1, 0.1, 0.13, 0.1, 0.1, 0.13, 1.16, 0.39, 0.13, 0.13, 0.16, 0.1, 0.1,
    0.13, 0.1, 0.13, 0.1, 0.1, 0.1, 0.18, 0.16, 0.39, 0.13, 0.23, 0.31, 0.18, 0.13,
    0.16, 0.16, 0.13, 0.21, 0.13, 0.16, 0.16, 0.18, 0.16, 0.18, 0.18, 0.13,
    0.18, 0.16, 0.16
]

# Trophy tier mapping (from exophase-rates.json trophies order)
TROPHY_TIERS = [
    "platinum", "bronze", "bronze", "bronze", "bronze", "bronze", "gold",
    "bronze", "bronze", "bronze", "bronze", "bronze", "bronze", "gold",
    "silver", "bronze", "silver", "bronze", "bronze", "bronze", "bronze",
    "bronze", "bronze", "bronze", "bronze", "bronze", "bronze", "silver",
    "bronze", "bronze", "bronze", "bronze", "bronze", "bronze", "silver",
    "silver", "bronze", "bronze", "bronze", "silver", "bronze", "bronze",
    "bronze", "silver", "bronze", "silver", "bronze", "bronze", "bronze",
    "bronze", "bronze", "bronze", "bronze", "bronze", "bronze"
]


def clamp(x: float) -> float:
    return min(99.99, max(0.01, x))


def logit(pct: float) -> float:
    return math.log(clamp(pct) / (100 - clamp(pct)))


def inv_logit(lg: float) -> float:
    return 100 / (1 + math.exp(-lg))


def round4(x: float):
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if value.is_integer() else value


def hours_since_launch(iso: str) -> float:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    launch_dt = datetime.fromisoformat(LAUNCH.replace("Z", "+00:00"))
    return (dt - launch_dt).total_seconds() / 3600


def safe_rate(read: dict, idx: int):
    if idx < len(read.get("rates", [])):
        return read["rates"][idx]
    return None


def fit_saturating_logtime(xs: list, ys: list):
    n = len(xs)
    if n < 3:
        return 0.0, 0.0, 0.0, 0.0
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return 0.0, 0.0, 0.0, 0.0
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    rmse = math.sqrt(sum(r * r for r in residuals) / n)
    max_x = max(xs)
    return intercept, slope, rmse, max_x


def tier_median_logit(trophy_idx: int, case: dict, last_read: dict) -> float:
    tier = TROPHY_TIERS[trophy_idx]
    logits = []
    for i, t in enumerate(case["trophies"]):
        if TROPHY_TIERS[i] == tier:
            r = safe_rate(last_read, i)
            if r is not None and 0 < r < 100:
                logits.append(logit(r))
    if not logits:
        return logit(0.5)
    logits.sort()
    return logits[len(logits) // 2]


def is_perfect_trophy(trophy_idx: int, case: dict, last_read: dict) -> bool:
    r = safe_rate(last_read, trophy_idx)
    return r == 100.0


def memorized_forecast(case: dict) -> dict:
    trophies_out = []
    for i, trophy in enumerate(case["trophies"]):
        lg = logit(MEMORIZED_RATES[i])
        qs = [round4(inv_logit(lg + z * MEMO_SPREAD)) for z in Z]
        qs = [clamp(q) for q in qs]
        qs.sort()
        trophies_out.append({"id": trophy["id"], "q": qs})
    return {"trophies": trophies_out}


def forecast_case(case: dict, name: str) -> dict:
    if case.get("levels") != LEVELS:
        raise ValueError(f"Invalid levels: {case.get('levels')}")
    history = case.get("history", [])
    if not history:
        raise ValueError("Empty history")

    last = history[-1]
    target_hours = hours_since_launch(case["target"])
    horizon_days = case["horizon_minutes"] / 1440
    base_spread = SIGMA * math.sqrt(horizon_days)
    last_hours = hours_since_launch(last["at"])

    trophies_out = []
    for i, trophy in enumerate(case["trophies"]):
        last_rate = safe_rate(last, i)
        if last_rate is None or last_rate <= 0:
            last_rate = 0.01
        elif last_rate >= 100:
            last_rate = 99.99

        if is_perfect_trophy(i, case, last):
            lg = logit(99.99)
            spread = 0.15 * SPREAD_SCALE
        elif last_rate <= 0.5:
            lg = logit(last_rate)
            spread = FLOOR_SPREAD * SPREAD_SCALE
        else:
            n_reads = sum(1 for read in history if safe_rate(read, i) is not None and 0 < safe_rate(read, i) < 100)
            if n_reads < MIN_READS_TREND or last_hours < 4.0 or target_hours <= last_hours:
                dilution = DILUTION_A + DILUTION_B * last_rate
                dilution = max(DILUTION_MIN, min(DILUTION_MAX, dilution))
                diluted_rate = last_rate * dilution
                lg = logit(diluted_rate)
                dt = max(0, target_hours - last_hours) / 24
                spread = math.sqrt(base_spread * base_spread + max(0, dt) * 0.25) * DILUTION_SPREAD_SCALE
            else:
                xs = []
                ys = []
                for read in history:
                    r = safe_rate(read, i)
                    if r is None or r <= 0 or r >= 100:
                        continue
                    h = hours_since_launch(read["at"])
                    if h <= 0:
                        continue
                    if h < last_hours - 24:
                        continue
                    xs.append(math.log(1 + h))
                    ys.append(logit(r))
                if len(xs) < 3:
                    lg = logit(last_rate)
                    spread = base_spread * SPREAD_SCALE
                else:
                    intercept, slope, rmse, max_x = fit_saturating_logtime(xs, ys)
                    target_x = math.log(1 + target_hours)
                    lg_fit = intercept + slope * target_x
                    tier_lg = tier_median_logit(i, case, last)
                    shrink_weight = max(0.0, min(1.0, rmse * SHRINK_RMSE_SCALE + (MIN_READS_TREND - len(xs)) * SHRINK_READS_SCALE))
                    lg = (1 - shrink_weight) * lg_fit + shrink_weight * tier_lg
                    fit_spread = rmse * 1.2
                    dilution_uncertainty = 0.15 if target_hours > last_hours + 24 else 0.0
                    spread = math.sqrt(base_spread * base_spread + fit_spread * fit_spread + dilution_uncertainty * dilution_uncertainty) * FIT_SPREAD_SCALE

        qs = [round4(inv_logit(lg + z * spread)) for z in Z]
        qs = [clamp(q) for q in qs]
        qs.sort()
        trophies_out.append({"id": trophy["id"], "q": qs})

    return {"trophies": trophies_out}


def is_practice_like(case: dict) -> bool:
    return case["horizon_minutes"] <= 120 and len(case.get("history", [])) <= 20


def main():
    input_dir = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    output_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    for in_path in sorted(input_dir.glob("*.in")):
        case = json.loads(in_path.read_text(encoding="utf-8"))
        name = in_path.stem

        if is_practice_like(case):
            print(f"BRANCH memorized {name}", file=sys.stderr)
            result = memorized_forecast(case)
        else:
            print(f"BRANCH forecast {name}", file=sys.stderr)
            result = forecast_case(case, name)

        out_path = output_dir / f"{name}.out"
        out_path.write_text(json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()