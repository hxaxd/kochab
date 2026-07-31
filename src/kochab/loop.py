"""A reference round. Domain-specific revision and judgment remain abstract.

The external evaluator owns execution and verification. An environment can be
queried during investigation. Between rounds, the Attributor port produces
attribution and the Curator port grows the benchmark from failed cases; the
loop implements none of these.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from kochab.model import Attribution, Benchmark, Candidate, Evaluation, Outcome
from kochab.port import Environment, Evaluator, Harness


@dataclass(frozen=True)
class Context:
    benchmark: Benchmark
    environment: Environment
    harness: Harness
    baseline: Evaluation
    attribution: Attribution


class Iteration(ABC):
    def __init__(self, evaluator: Evaluator):
        self.evaluator = evaluator

    @abstractmethod
    def revise(self, context: Context) -> Candidate:
        """Investigate the evidence and produce a domain-specific candidate."""

    @abstractmethod
    def decide(self, context: Context, trial: Evaluation) -> bool:
        """Judge the observed result against this domain's requirements."""

    def run(self, context: Context) -> Outcome:
        candidate = self.revise(context)
        trial = self.evaluator.run(candidate, context.benchmark)
        return Outcome(candidate, trial, self.decide(context, trial))
