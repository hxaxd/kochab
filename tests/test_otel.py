from __future__ import annotations

import json
from pathlib import Path

from kochab.adapters.otel import OtelFileTracePort
from kochab.contracts.models import TraceFilter


def _attr(key: str, value: object) -> dict:
    if isinstance(value, float):
        wrapped = {"doubleValue": value}
    else:
        wrapped = {"stringValue": str(value)}
    return {"key": key, "value": wrapped}


def test_otlp_genai_and_openinference_are_projected(tmp_path: Path) -> None:
    path = tmp_path / "otel.jsonl"
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", "agent-service")]},
                "scopeSpans": [
                    {
                        "scope": {"name": "test.instrumentation", "version": "1.0"},
                        "spans": [
                            {
                                "traceId": "a" * 32,
                                "spanId": "b" * 16,
                                "name": "invoke_agent planner",
                                "startTimeUnixNano": "1750000000000000000",
                                "endTimeUnixNano": "1750000001000000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    _attr("gen_ai.operation.name", "invoke_agent"),
                                    _attr("gen_ai.agent.name", "planner"),
                                    _attr("openinference.span.kind", "AGENT"),
                                    _attr("input.value", '{"question":"hello"}'),
                                    _attr("output.value", '{"answer":"world"}'),
                                    _attr("trace.evaluations.0.evaluation.name", "correctness"),
                                    _attr("trace.evaluations.0.evaluation.score", 0.25),
                                    _attr("annotations.0.annotation.name", "thumbs"),
                                    _attr("annotations.0.annotation.label", "negative"),
                                    _attr("annotations.0.annotation.annotator_kind", "human"),
                                    _attr("braintrust.scores", '{"safety":0.75}'),
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    port = OtelFileTracePort(path)

    refs = port.query(TraceFilter(max_feedback_score=0.5))
    assert len(refs) == 1
    assert refs[0].feedback_scores == {"correctness": 0.25, "safety": 0.75}
    assert refs[0].has_human_feedback is True

    trace = port.read(refs[0])
    assert trace.resource["service.name"] == "agent-service"
    assert trace.spans[0].kind == "invoke_agent"
    assert trace.spans[0].input == '{"question":"hello"}'
    assert {item.name for item in trace.feedback} == {"correctness", "thumbs", "safety"}


def test_otlp_runtime_status_is_distinct_from_eval_quality(tmp_path: Path) -> None:
    path = tmp_path / "otel.json"
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "1" * 32,
                                "spanId": "2" * 16,
                                "name": "execute_tool search",
                                "status": {"code": "STATUS_CODE_ERROR"},
                                "attributes": [_attr("gen_ai.operation.name", "execute_tool")],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    port = OtelFileTracePort(path)
    refs = port.query(TraceFilter(status="error"))
    assert len(refs) == 1
    assert refs[0].feedback_scores == {}
