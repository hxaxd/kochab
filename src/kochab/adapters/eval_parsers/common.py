from __future__ import annotations

import json
from typing import Any

from kochab.contracts.models import CaseScore


class EvalFormatError(ValueError):
    pass


def case(
    *, id: str, score: float, passed: Any, feedback: str, output: str,
    metrics: Any, threshold: float,
) -> CaseScore:
    return CaseScore(
        id=id,
        score=score,
        passed=bool(passed) if passed is not None else score >= threshold,
        feedback=feedback,
        output=output,
        metrics=numeric_mapping(metrics),
    )


def json_value(payload: str) -> Any:
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise EvalFormatError(f"invalid JSON eval output: {payload[:300]}") from exc


def numeric_mapping(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): float(item)
        for key, item in value.items()
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    }


def mean(values: Any) -> float:
    rows = list(values)
    return sum(rows) / len(rows) if rows else 0.0
