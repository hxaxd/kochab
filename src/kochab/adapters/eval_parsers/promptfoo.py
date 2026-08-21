from __future__ import annotations

from kochab.adapters.eval_parsers.common import EvalFormatError, case, json_value, mean, numeric_mapping
from kochab.contracts.models import EvalResult


def parse(payload: str, threshold: float) -> EvalResult:
    data = json_value(payload)
    if not isinstance(data, dict):
        raise EvalFormatError("promptfoo output must be a JSON object")
    envelope = data.get("results", data)
    if isinstance(envelope, list):
        rows, stats = envelope, {}
    elif isinstance(envelope, dict):
        rows = envelope.get("results") or envelope.get("outputs") or []
        stats = envelope.get("stats") or {}
    else:
        raise EvalFormatError("promptfoo output has no result collection")
    cases = []
    for index, row in enumerate(rows):
        grading = row.get("gradingResult") or row.get("grading") or {}
        response = row.get("response") or {}
        score = float(row.get("score", grading.get("score", 0.0)) or 0.0)
        case_id = row.get("id") or row.get("testId") or row.get("testIdx")
        output = response.get("output") if isinstance(response, dict) else response
        cases.append(
            case(
                id=str(case_id if case_id is not None else f"case-{index}"),
                score=score, passed=row.get("success", grading.get("pass")),
                feedback=str(row.get("error") or grading.get("reason") or row.get("reason") or ""),
                output=str(output or row.get("output") or ""), metrics=None, threshold=threshold,
            )
        )
    return EvalResult(
        score=mean(item.score for item in cases),
        passed=bool(cases) and all(item.passed for item in cases),
        cases=cases,
        metrics=numeric_mapping(stats),
    )
