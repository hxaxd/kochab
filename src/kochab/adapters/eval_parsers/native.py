from __future__ import annotations

import json

from kochab.adapters.eval_parsers.common import EvalFormatError, case, json_value, mean, numeric_mapping
from kochab.contracts.models import EvalResult


def parse_json(payload: str, threshold: float) -> EvalResult:
    data = json_value(payload)
    if not isinstance(data, dict):
        raise EvalFormatError("kochab eval output must be a JSON object")
    cases = [
        case(
            id=str(row["id"]), score=float(row.get("score", 0.0)), passed=row.get("passed"),
            feedback=str(row.get("feedback") or ""), output=str(row.get("output") or ""),
            metrics=row.get("metrics"), threshold=threshold,
        )
        for row in data.get("cases") or []
    ]
    score = float(data.get("score", mean(item.score for item in cases)))
    passed = bool(data["passed"]) if "passed" in data else bool(cases) and all(item.passed for item in cases)
    return EvalResult(score=score, passed=passed, cases=cases, metrics=numeric_mapping(data.get("metrics")))


def parse_jsonl(payload: str, threshold: float) -> EvalResult:
    rows = []
    for number, line in enumerate(payload.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalFormatError(f"invalid eval JSONL at line {number}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise EvalFormatError(f"eval JSONL line {number} must be an object")
        rows.append(row)
    cases = []
    for index, row in enumerate(rows):
        score = float(row.get("score", 0.0) or 0.0)
        cases.append(
            case(
                id=str(row.get("id") or row.get("case_id") or row.get("sample_id") or f"case-{index}"),
                score=score, passed=row.get("passed", row.get("success")),
                feedback=str(row.get("feedback") or row.get("reason") or row.get("error") or ""),
                output=str(row.get("output") or row.get("response") or ""),
                metrics=row.get("metrics"), threshold=threshold,
            )
        )
    return EvalResult(
        score=mean(item.score for item in cases),
        passed=bool(cases) and all(item.passed for item in cases),
        cases=cases,
    )
