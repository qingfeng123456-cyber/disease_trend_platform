from __future__ import annotations

import math
from typing import Iterable


def regression_metrics(actual: Iterable[float], predicted: Iterable[float]) -> dict[str, float]:
    pairs = [(float(a), float(p)) for a, p in zip(actual, predicted) if a is not None and p is not None]
    if not pairs:
        return {"mae": 0.0, "rmse": 0.0, "r2": 0.0, "mape": 0.0, "smape": 0.0}
    y = [a for a, _ in pairs]
    pred = [p for _, p in pairs]
    n = len(pairs)
    mae = sum(abs(a - p) for a, p in pairs) / n
    rmse = math.sqrt(sum((a - p) ** 2 for a, p in pairs) / n)
    mean_y = sum(y) / n
    ss_tot = sum((a - mean_y) ** 2 for a in y)
    ss_res = sum((a - p) ** 2 for a, p in pairs)
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    nonzero = [(a, p) for a, p in pairs if a != 0]
    mape = sum(abs((a - p) / a) for a, p in nonzero) / len(nonzero) if nonzero else 0.0
    smape = sum((2 * abs(p - a) / (abs(a) + abs(p))) if (abs(a) + abs(p)) else 0 for a, p in pairs) / n
    return {
        "mae": round(mae, 6),
        "rmse": round(rmse, 6),
        "r2": round(r2, 6),
        "mape": round(mape, 6),
        "smape": round(smape, 6),
    }
