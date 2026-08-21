from __future__ import annotations

import gzip
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class OtlpReceiverError(ValueError):
    pass


class OtlpFileSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, body: bytes, content_type: str, content_encoding: str = "") -> str:
        if content_encoding.lower() == "gzip":
            try:
                body = gzip.decompress(body)
            except OSError as exc:
                raise OtlpReceiverError("invalid gzip OTLP body") from exc
        if "json" in content_type:
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OtlpReceiverError("invalid OTLP JSON body") from exc
            response_type = "json"
        elif "protobuf" in content_type or content_type in {"", "application/octet-stream"}:
            payload = _protobuf_to_json(body)
            response_type = "protobuf"
        else:
            raise OtlpReceiverError(f"unsupported OTLP content type: {content_type}")
        if not isinstance(payload, dict) or not (
            payload.get("resourceSpans") or payload.get("resource_spans")
        ):
            raise OtlpReceiverError("OTLP trace request contains no resource spans")
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
        return response_type


def make_server(
    sink: OtlpFileSink,
    host: str = "127.0.0.1",
    port: int = 4318,
    max_body_bytes: int = 32 * 1024 * 1024,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path.rstrip("/") != "/v1/traces":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400, "invalid content length")
                return
            if length <= 0 or length > max_body_bytes:
                self.send_error(413 if length > max_body_bytes else 400)
                return
            body = self.rfile.read(length)
            try:
                response_type = sink.append(
                    body,
                    self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower(),
                    self.headers.get("Content-Encoding", ""),
                )
            except OtlpReceiverError as exc:
                self.send_error(400, str(exc))
                return
            if response_type == "protobuf":
                from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
                    ExportTraceServiceResponse,
                )

                response = ExportTraceServiceResponse().SerializeToString()
                content_type = "application/x-protobuf"
            else:
                response = b"{}"
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


@contextmanager
def serve_in_thread(
    sink: OtlpFileSink,
    host: str = "127.0.0.1",
    port: int = 4318,
) -> Iterator[ThreadingHTTPServer]:
    server = make_server(sink, host, port)
    thread = threading.Thread(target=server.serve_forever, name="kochab-otlp", daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _protobuf_to_json(body: bytes) -> dict[str, Any]:
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    request = ExportTraceServiceRequest()
    try:
        request.ParseFromString(body)
    except Exception as exc:
        raise OtlpReceiverError("invalid OTLP protobuf body") from exc
    return MessageToDict(request, preserving_proto_field_name=False)
