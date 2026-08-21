from __future__ import annotations

import gzip
import json
import urllib.request
from pathlib import Path

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

from kochab.adapters.otel import OtelFileTracePort
from kochab.contracts.models import TraceFilter
from kochab.otlp_receiver import OtlpFileSink, serve_in_thread


def _payload(trace_id: str) -> dict:
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": "b" * 16,
                                "name": "invoke_agent test",
                                "attributes": [
                                    {
                                        "key": "gen_ai.operation.name",
                                        "value": {"stringValue": "invoke_agent"},
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }


def test_otlp_http_accepts_json_and_protobuf(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    with serve_in_thread(OtlpFileSink(path), port=0) as server:
        endpoint = f"http://127.0.0.1:{server.server_port}/v1/traces"
        raw_json = json.dumps(_payload("1" * 32)).encode()
        request = urllib.request.Request(
            endpoint,
            data=gzip.compress(raw_json),
            headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 200

        message = ExportTraceServiceRequest()
        span = message.resource_spans.add().scope_spans.add().spans.add()
        span.trace_id = bytes.fromhex("2" * 32)
        span.span_id = bytes.fromhex("b" * 16)
        span.name = "invoke_agent test"
        attribute = span.attributes.add()
        attribute.key = "gen_ai.operation.name"
        attribute.value.string_value = "invoke_agent"
        request = urllib.request.Request(
            endpoint,
            data=message.SerializeToString(),
            headers={"Content-Type": "application/x-protobuf"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 200

    refs = OtelFileTracePort(path).query(TraceFilter(limit=10))
    assert {ref.trace_id for ref in refs} == {"1" * 32, "2" * 32}
