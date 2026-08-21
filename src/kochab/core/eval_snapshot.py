from __future__ import annotations

from typing import Any

from kochab.contracts.models import EvalResult, Version


def eval_snapshot(
    result: EvalResult,
    version: Version,
    requested: list[str],
    expected: set[str],
) -> dict[str, Any]:
    returned = {row.id for row in result.cases}
    return {
        "score": result.score,
        "passed": result.passed,
        "n": len(result.cases),
        "passed_cases": sum(1 for row in result.cases if row.passed),
        "version": version,
        "case_ids": requested,
        "complete": set(requested) == expected and returned == expected,
        "metrics": dict(result.metrics),
        "cases": [row.model_dump() for row in result.cases],
    }
