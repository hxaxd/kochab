from __future__ import annotations

import xml.etree.ElementTree as ET

from kochab.adapters.eval_parsers.common import EvalFormatError, mean
from kochab.contracts.models import CaseScore, EvalResult


def parse(payload: str, threshold: float) -> EvalResult:
    del threshold
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise EvalFormatError(f"invalid JUnit XML: {exc}") from exc
    cases = []
    for index, node in enumerate(root.iter("testcase")):
        problem = next(
            (child for tag in ("failure", "error", "skipped") if (child := node.find(tag)) is not None),
            None,
        )
        passed = problem is None
        feedback = ""
        if problem is not None:
            feedback = problem.get("message") or (problem.text or "").strip() or problem.tag
        case_id = node.get("id") or node.get("name") or f"case-{index}"
        if node.get("classname"):
            case_id = f"{node.get('classname')}::{case_id}"
        cases.append(CaseScore(
            id=case_id, score=1.0 if passed else 0.0, passed=passed, feedback=feedback,
            output=(node.findtext("system-out") or "").strip(),
        ))
    score = mean(item.score for item in cases)
    return EvalResult(score=score, passed=bool(cases) and all(item.passed for item in cases), cases=cases)
