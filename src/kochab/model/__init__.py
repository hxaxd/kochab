"""The domain relationships in evaluation-driven harness development.

Artifacts identify domain-owned content. They need not be files, text, or scores.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Artifact:
    ref: str
    description: str


@dataclass(frozen=True)
class Candidate:
    ref: str


@dataclass(frozen=True)
class Task:
    id: str
    goal: str
    initial_state: Artifact
    verifier: Artifact


@dataclass(frozen=True)
class Benchmark:
    name: str
    tasks: tuple[Task, ...]


@dataclass(frozen=True)
class CaseResult:
    task_id: str
    passed: bool
    feedback: str
    trace: Artifact


@dataclass(frozen=True)
class Evaluation:
    candidate: Candidate
    cases: tuple[CaseResult, ...]


@dataclass(frozen=True)
class Finding:
    target: str
    explanation: str
    evidence: tuple[Artifact, ...]


@dataclass(frozen=True)
class Attribution:
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class Outcome:
    candidate: Candidate
    evaluation: Evaluation
    keep: bool
