from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from kochab.contracts.models import Feedback, Span, Trace


def span_kind(raw: Mapping[str, Any], attrs: Mapping[str, Any]) -> str:
    operation = attrs.get("gen_ai.operation.name")
    if operation:
        return str(operation)
    inference = attrs.get("openinference.span.kind")
    if inference:
        return str(inference).lower()
    return str(raw.get("kind") or "internal").lower()


def content(attrs: Mapping[str, Any], direction: str) -> str | None:
    keys = (
        f"gen_ai.{direction}.messages",
        f"{direction}.value",
        f"{direction}.value.json",
        f"braintrust.{direction}",
        f"braintrust.{direction}_json",
        "inputs" if direction == "input" else "outputs",
    )
    for key in keys:
        value = attrs.get(key)
        if value is not None:
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return None


def assemble(trace_id: str, spans: list[Span], resource: dict[str, Any]) -> Trace:
    spans.sort(key=lambda item: item.start_time or datetime.min.replace(tzinfo=timezone.utc))
    timestamp = next((span.start_time for span in spans if span.start_time), datetime.now(timezone.utc))
    status = "error" if any(span.status == "error" for span in spans) else "ok"
    feedback: list[Feedback] = []
    human_feedback: list[str] = []
    for span in spans:
        feedback.extend(feedback_from_attributes(span.attributes))
        for event in span.events:
            if event.name == "gen_ai.evaluation.result":
                feedback.extend(feedback_from_attributes(event.attributes, prefix="gen_ai.evaluation."))
            if event.name in {"human.feedback", "gen_ai.user.feedback"}:
                text = event.attributes.get("content") or event.attributes.get("feedback")
                if text:
                    human_feedback.append(str(text))
    return Trace(
        ref=trace_id,
        trace_id=trace_id,
        timestamp=timestamp,
        status=status,
        spans=spans,
        human_feedback="\n".join(human_feedback) or None,
        feedback=feedback,
        resource=resource,
    )


def feedback_from_attributes(attrs: Mapping[str, Any], prefix: str = "") -> list[Feedback]:
    if prefix:
        name = attrs.get(f"{prefix}name") or attrs.get("name")
        if not name:
            return []
        return [Feedback(
            name=str(name),
            score=_float(_first_present(attrs, f"{prefix}score", "score")),
            label=_string(attrs.get(f"{prefix}label") or attrs.get("label")),
            explanation=_string(attrs.get(f"{prefix}explanation") or attrs.get("explanation")),
            source=_string(attrs.get(f"{prefix}source") or attrs.get("source")) or "evaluator",
        )]
    results = _braintrust_feedback(attrs)
    for scope in ("", "trace.", "session."):
        for collection, source in (("evaluations", "evaluator"), ("annotations", "human")):
            index = 0
            while True:
                singular = "evaluation" if collection == "evaluations" else "annotation"
                base = f"{scope}{collection}.{index}.{singular}"
                name = attrs.get(f"{base}.name")
                if name is None:
                    break
                results.append(Feedback(
                    name=str(name),
                    score=_float(attrs.get(f"{base}.score")),
                    label=_string(attrs.get(f"{base}.label")),
                    explanation=_string(attrs.get(f"{base}.explanation")),
                    source=_string(attrs.get(f"{base}.annotator_kind")) or source,
                ))
                index += 1
    return results


def _braintrust_feedback(attrs: Mapping[str, Any]) -> list[Feedback]:
    scores = attrs.get("braintrust.scores")
    if isinstance(scores, str):
        try:
            scores = json.loads(scores)
        except json.JSONDecodeError:
            scores = None
    results = []
    if isinstance(scores, dict):
        results.extend(
            Feedback(name=str(name), score=_float(score), source="evaluator")
            for name, score in scores.items()
        )
    results.extend(
        Feedback(name=key.removeprefix("braintrust.scores."), score=_float(value), source="evaluator")
        for key, value in attrs.items()
        if key.startswith("braintrust.scores.")
    )
    return results


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _first_present(attrs: Mapping[str, Any], primary: str, fallback: str) -> Any:
    value = attrs.get(primary)
    return attrs.get(fallback) if value is None else value
