"""Domain interfaces; no attributor, curator, environment, evaluator, or harness is supplied here."""
from typing import Any, Protocol

from kochab.model import Artifact, Attribution, Benchmark, Candidate, Evaluation, Task


class Environment(Protocol):
    def describe(self) -> str: ...

    def restore(self, task: Task) -> Any: ...

    def observe(self, state: Any) -> Any: ...

    def act(self, state: Any, action: Any) -> Any: ...


class Harness(Protocol):
    def describe(self) -> str: ...

    def inspect(self, artifact: Artifact) -> object: ...


class Evaluator(Protocol):
    def run(self, candidate: Candidate, benchmark: Benchmark) -> Evaluation: ...


class Attributor(Protocol):
    def run(self, evaluation: Evaluation) -> Attribution: ...


class Curator(Protocol):
    def grow(self, benchmark: Benchmark, evaluation: Evaluation) -> Benchmark: ...
