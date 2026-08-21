from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from kochab.contracts.models import EvalResult, SuiteInfo, Version
from kochab.contracts.protocols import EvalPort


class HiddenCase(PermissionError):
    """Raised when the evolution agent asks about a holdout case."""


class GatedEvalPort:
    """EvalPort the model sees: holdout ids are absent and unnameable."""

    def __init__(self, inner: EvalPort, holdout_ids: set[str]) -> None:
        self._inner = inner
        self._holdout = set(holdout_ids)

    def suites(self) -> list[SuiteInfo]:
        return [s for s in self._inner.suites() if s.id not in self._holdout]

    def criteria(self) -> str:
        return self._inner.criteria()

    def gold(self, case_id: str) -> str | None:
        self._check(case_id)
        return self._inner.gold(case_id)

    def run(
        self,
        case_ids: list[str],
        surface_version: Version,
        visibility: str = "train",
    ) -> EvalResult:
        if not case_ids:
            case_ids = [s.id for s in self.suites()]
        for case_id in case_ids:
            self._check(case_id)
        return self._inner.run(case_ids, surface_version, visibility="train")

    def train_ids(self) -> list[str]:
        return [s.id for s in self.suites()]

    def _check(self, case_id: str) -> None:
        if case_id in self._holdout:
            raise HiddenCase(f"unknown case: {case_id}")
        known = {s.id for s in self._inner.suites()}
        if case_id not in known:
            raise HiddenCase(f"unknown case: {case_id}")


class HoldoutGate:
    """Runs holdout outside the evolution toolset. Model never sees per-case text."""

    def __init__(
        self,
        eval_port: EvalPort,
        holdout_ids: list[str],
        baseline_path: Path,
    ) -> None:
        self.eval_port = eval_port
        self.holdout_ids = list(holdout_ids)
        self.baseline_path = baseline_path
        self._pending: tuple[Version, EvalResult, dict] | None = None

    def capture_if_missing(self, version: Version) -> dict:
        if self.baseline_path.exists():
            return json.loads(self.baseline_path.read_text(encoding="utf-8"))
        return self._write_baseline(
            self.eval_port.run(self.holdout_ids, version, visibility="holdout")
        )

    def check(self, version: Version) -> dict:
        if not self.baseline_path.exists():
            raise RuntimeError("holdout baseline not captured")
        baseline = json.loads(self.baseline_path.read_text(encoding="utf-8"))
        result = self.eval_port.run(self.holdout_ids, version, visibility="holdout")
        self._pending = (version, result, baseline)
        current = {c.id: c.score for c in result.cases}
        if set(current) != set(self.holdout_ids):
            return {
                "passed": False,
                "score": result.score,
                "baseline_score": baseline.get("score", 0.0),
                "n": len(self.holdout_ids),
                "regressions": len(self.holdout_ids),
            }
        old = baseline.get("cases", {})
        regressions = [
            case_id
            for case_id, score in current.items()
            if score < float(old.get(case_id, 0.0)) - 1e-9
        ]
        passed = not regressions
        report = {
            "passed": passed,
            "score": result.score,
            "baseline_score": baseline.get("score", 0.0),
            "n": len(self.holdout_ids),
            "regressions": len(regressions),
        }
        return report

    def commit(self, version: Version) -> dict:
        if self._pending is None or self._pending[0] != version:
            report = self.check(version)
            if not report["passed"]:
                raise RuntimeError("cannot commit a failing holdout gate")
        assert self._pending is not None
        _, result, baseline = self._pending
        payload = self._write_baseline(result, merge_max=baseline.get("cases", {}))
        self._pending = None
        return payload

    def _write_baseline(self, result: EvalResult, merge_max: dict | None = None) -> dict:
        cases = {}
        for row in result.cases:
            prev = float((merge_max or {}).get(row.id, 0.0))
            cases[row.id] = max(prev, row.score)
        payload = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "score": sum(cases.values()) / len(cases) if cases else 0.0,
            "cases": cases,
        }
        self.baseline_path.parent.mkdir(parents=True, exist_ok=True)
        fd, raw = tempfile.mkstemp(
            prefix=f".{self.baseline_path.name}.", dir=self.baseline_path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(raw, self.baseline_path)
        except BaseException:
            try:
                os.unlink(raw)
            except FileNotFoundError:
                pass
            raise
        return payload
