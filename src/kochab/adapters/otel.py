from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from kochab.adapters.otel_decode import OtelDecodeError, load_traces
from kochab.contracts.models import Trace, TraceFilter, TraceRef


class OtelFileTracePort:
    """Read OTLP/HTTP JSON requests carrying GenAI or OpenInference spans."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def query(self, filter: TraceFilter) -> list[TraceRef]:
        traces = sorted(self._traces(), key=lambda row: row.timestamp, reverse=True)
        refs = []
        for trace in traces:
            if not _matches(trace, filter):
                continue
            has_human = bool(trace.human_feedback) or any(
                item.source.lower() == "human" for item in trace.feedback
            )
            refs.append(TraceRef(
                ref=trace.ref,
                trace_id=trace.trace_id,
                timestamp=trace.timestamp,
                status=trace.status,
                feedback_scores={item.name: item.score for item in trace.feedback if item.score is not None},
                feedback_labels={item.name: item.label for item in trace.feedback if item.label is not None},
                has_human_feedback=has_human,
            ))
            if len(refs) >= filter.limit:
                break
        return refs

    def read(self, ref: TraceRef) -> Trace:
        for trace in self._traces():
            if trace.ref == ref.ref or trace.trace_id == ref.trace_id:
                return trace
        raise KeyError(ref.ref)

    def subscribe(self, filter: TraceFilter) -> Iterator[TraceRef]:
        yield from self.query(filter)

    def _traces(self) -> list[Trace]:
        if not self.path.exists() or not self.path.read_text(encoding="utf-8").strip():
            return []
        return load_traces(self.path)


def _matches(trace: Trace, filter: TraceFilter) -> bool:
    if filter.status and trace.status != filter.status:
        return False
    if filter.since and trace.timestamp < filter.since:
        return False
    if filter.until and trace.timestamp > filter.until:
        return False
    has_human = bool(trace.human_feedback) or any(
        item.source.lower() == "human" for item in trace.feedback
    )
    if filter.has_human_feedback is not None and has_human != filter.has_human_feedback:
        return False
    selected = [
        item for item in trace.feedback if not filter.feedback_name or item.name == filter.feedback_name
    ]
    if filter.feedback_name and not selected:
        return False
    if filter.max_feedback_score is not None and not any(
        item.score is not None and item.score <= filter.max_feedback_score
        for item in selected or trace.feedback
    ):
        return False
    return True


__all__ = ["OtelDecodeError", "OtelFileTracePort"]
