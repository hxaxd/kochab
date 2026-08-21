from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field

Version = str
Category = Literal["knowledge", "experience", "tool", "process"]


class UnitManifest(BaseModel):
    id: str
    category: Category
    path: str
    format: str = "text"
    max_bytes: int | None = None
    fingerprint: str = ""


class SurfaceManifest(BaseModel):
    units: list[UnitManifest]
    version: Version


class Change(BaseModel):
    unit_id: str
    content: str


class SuiteInfo(BaseModel):
    id: str
    label: str = ""
    question: str = ""


class CaseScore(BaseModel):
    id: str
    score: float
    passed: bool
    feedback: str
    output: str = ""
    metrics: Mapping[str, float] = Field(default_factory=dict)


class EvalResult(BaseModel):
    score: float
    passed: bool
    cases: list[CaseScore]
    metrics: Mapping[str, float] = Field(default_factory=dict)


class TraceFilter(BaseModel):
    since: datetime | None = None
    until: datetime | None = None
    status: str | None = None
    has_human_feedback: bool | None = None
    feedback_name: str | None = None
    max_feedback_score: float | None = None
    limit: int = 50


class TraceRef(BaseModel):
    ref: str
    trace_id: str
    timestamp: datetime
    status: str = "unknown"
    feedback_scores: Mapping[str, float] = Field(default_factory=dict)
    feedback_labels: Mapping[str, str] = Field(default_factory=dict)
    has_human_feedback: bool = False


class SpanEvent(BaseModel):
    name: str
    timestamp: datetime | None = None
    attributes: Mapping[str, Any] = Field(default_factory=dict)


class Span(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: str = "unset"
    kind: str = "internal"
    attributes: Mapping[str, Any] = Field(default_factory=dict)
    events: list[SpanEvent] = Field(default_factory=list)
    input: str | None = None
    output: str | None = None


class Feedback(BaseModel):
    name: str
    score: float | None = None
    label: str | None = None
    explanation: str | None = None
    source: str = "unknown"


class Trace(BaseModel):
    ref: str
    trace_id: str
    timestamp: datetime
    status: str
    spans: list[Span] = Field(default_factory=list)
    human_feedback: str | None = None
    feedback: list[Feedback] = Field(default_factory=list)
    resource: Mapping[str, Any] = Field(default_factory=dict)
