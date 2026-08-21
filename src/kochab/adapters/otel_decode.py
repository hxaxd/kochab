from __future__ import annotations

import base64
import json
from collections import defaultdict
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kochab.adapters.otel_semantics import assemble, content, span_kind
from kochab.contracts.models import Span, SpanEvent, Trace


class OtelDecodeError(ValueError):
    pass


def load_traces(path: Path) -> list[Trace]:
    groups: dict[str, list[Span]] = defaultdict(list)
    resources: dict[str, dict[str, Any]] = {}
    for payload in _load_payloads(path):
        for span, resource in _decode_request(payload):
            groups[span.trace_id].append(span)
            resources.setdefault(span.trace_id, {}).update(resource)
    return [assemble(trace_id, spans, resources.get(trace_id, {})) for trace_id, spans in groups.items()]


def _load_payloads(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        values = []
        lines = text.splitlines()
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError as exc:
                if number == len(lines) and not path.read_bytes().endswith(b"\n"):
                    break
                raise OtelDecodeError(f"invalid OTLP JSONL at line {number}: {exc.msg}") from exc
        return values
    return value if isinstance(value, list) else [value]


def _decode_request(payload: Any) -> Iterator[tuple[Span, dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise OtelDecodeError("OTLP payload must be an object")
    resource_spans = payload.get("resourceSpans") or payload.get("resource_spans")
    if resource_spans is None:
        if "traceId" in payload or "trace_id" in payload:
            yield _decode_span(payload), {}
            return
        raise OtelDecodeError("payload has no resourceSpans")
    for resource_block in resource_spans:
        resource = attributes((resource_block.get("resource") or {}).get("attributes") or [])
        scopes = resource_block.get("scopeSpans") or resource_block.get("scope_spans") or []
        for scope_block in scopes:
            scope = scope_block.get("scope") or {}
            scope_attrs = {"otel.scope.name": scope.get("name", ""), "otel.scope.version": scope.get("version", "")}
            for raw in scope_block.get("spans") or []:
                span = _decode_span(raw)
                span.attributes = {**scope_attrs, **span.attributes}
                yield span, resource


def _decode_span(raw: Mapping[str, Any]) -> Span:
    trace_id = _otel_id(raw.get("traceId") or raw.get("trace_id"), 16)
    span_id = _otel_id(raw.get("spanId") or raw.get("span_id"), 8)
    if not trace_id or not span_id:
        raise OtelDecodeError("every span requires traceId and spanId")
    attrs = attributes(raw.get("attributes") or {})
    events = [SpanEvent(
        name=str(event.get("name") or "event"),
        timestamp=nano_time(event.get("timeUnixNano") or event.get("time_unix_nano")),
        attributes=attributes(event.get("attributes") or {}),
    ) for event in raw.get("events") or []]
    status_raw = raw.get("status") or {}
    status = str(status_raw.get("code") or raw.get("status") or "unset").lower()
    status = "error" if "error" in status else "ok" if "ok" in status else status
    return Span(
        trace_id=trace_id, span_id=span_id,
        parent_span_id=_otel_id(raw.get("parentSpanId") or raw.get("parent_span_id"), 8) or None,
        name=str(raw.get("name") or attrs.get("gen_ai.operation.name") or "span"),
        start_time=nano_time(raw.get("startTimeUnixNano") or raw.get("start_time_unix_nano")),
        end_time=nano_time(raw.get("endTimeUnixNano") or raw.get("end_time_unix_nano")),
        status=status, kind=span_kind(raw, attrs), attributes=attrs, events=events,
        input=content(attrs, "input"), output=content(attrs, "output"),
    )


def attributes(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return {str(key): any_value(value) for key, value in raw.items()}
    return {
        str(item["key"]): any_value(item.get("value"))
        for item in raw
        if isinstance(item, dict) and "key" in item
    }


def any_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    casts = {"stringValue": str, "boolValue": bool, "intValue": int, "doubleValue": float, "bytesValue": str}
    for name, cast in casts.items():
        if name in value:
            try:
                return cast(value[name])
            except (TypeError, ValueError):
                return value[name]
    array = value.get("arrayValue") or value.get("array_value")
    if isinstance(array, dict):
        return [any_value(item) for item in array.get("values") or []]
    kvlist = value.get("kvlistValue") or value.get("kvlist_value")
    if isinstance(kvlist, dict):
        return attributes(kvlist.get("values") or [])
    return {key: any_value(item) for key, item in value.items()}


def nano_time(raw: Any) -> datetime | None:
    if raw in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(raw) / 1_000_000_000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                pass
        return None


def _otel_id(raw: Any, size: int) -> str:
    if raw in (None, ""):
        return ""
    if isinstance(raw, bytes):
        return raw.hex()
    value = str(raw)
    if len(value) == size * 2:
        try:
            bytes.fromhex(value)
            return value.lower()
        except ValueError:
            pass
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return value
    return decoded.hex() if len(decoded) == size else value
