from __future__ import annotations

import json
from typing import Any

from kochab.adapters.eval_parsers.common import EvalFormatError, json_value, mean
from kochab.contracts.models import CaseScore, EvalResult


def parse(payload: str, threshold: float) -> EvalResult:
    data = json_value(payload)
    if not isinstance(data, dict):
        raise EvalFormatError("Inspect log must be a JSON object")
    cases = []
    for index, row in enumerate(data.get("samples") or []):
        raw_scores = row.get("scores") or {}
        scores = list(raw_scores.values()) if isinstance(raw_scores, dict) else list(raw_scores)
        numeric, passed_values, explanations = [], [], []
        for raw in scores:
            value = raw.get("value") if isinstance(raw, dict) else raw
            score, passed = _score(value, threshold)
            numeric.append(score)
            passed_values.append(passed)
            if isinstance(raw, dict) and raw.get("explanation"):
                explanations.append(str(raw["explanation"]))
        cases.append(CaseScore(
            id=str(row.get("id") or row.get("uuid") or f"sample-{index}"),
            score=mean(numeric), passed=bool(scores) and all(passed_values),
            feedback="\n".join(explanations), output=_output(row),
            metrics={f"score_{i}": value for i, value in enumerate(numeric)},
        ))
    score = mean(item.score for item in cases)
    status_ok = str(data.get("status", "success")).lower() == "success"
    return EvalResult(
        score=score,
        passed=status_ok and bool(cases) and all(item.passed for item in cases),
        cases=cases,
    )


def _score(value: Any, threshold: float) -> tuple[float, bool]:
    if isinstance(value, bool):
        return (1.0 if value else 0.0), value
    if isinstance(value, (int, float)):
        score = float(value)
        return score, score >= threshold
    passed = str(value or "").strip().lower() in {"pass", "passed", "correct", "success", "true", "c"}
    return (1.0 if passed else 0.0), passed


def _output(row: dict[str, Any]) -> str:
    output = row.get("output")
    if isinstance(output, str):
        return output
    if output is not None:
        return json.dumps(output, ensure_ascii=False)
    messages = row.get("messages") or []
    if messages and isinstance(messages[-1], dict):
        return str(messages[-1].get("content") or "")
    return ""
