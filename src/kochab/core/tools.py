from __future__ import annotations

import json
from typing import Any, Callable

from kochab.adapters.files import FileSurface, SurfaceError
from kochab.contracts.models import Change, TraceFilter
from kochab.core.eval_snapshot import eval_snapshot
from kochab.gate.holdout import GatedEvalPort, HiddenCase, HoldoutGate
from kochab.core.tool_schemas import evolve_tool_schemas
from kochab.state import KochabState

_UNAVAILABLE = "unknown case"


def _ok(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _err(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


class EvolveTools:
    """The only tools the evolution model has. Holdout is not among them."""

    def __init__(
        self,
        surface: FileSurface,
        eval_port: GatedEvalPort,
        traces: Any,
        gate: HoldoutGate,
        state: KochabState,
    ) -> None:
        self.surface = surface
        self.eval_port = eval_port
        self.traces = traces
        self.gate = gate
        self.state = state
        self.finished = False
        self.outcome: dict[str, Any] | None = None
        self.round_start = surface.accepted()
        self.last_eval: dict[str, Any] | None = None
        self.first_eval: dict[str, Any] | None = None
        self._handlers: dict[str, Callable[..., str]] = {
            "surface_manifest": self._manifest,
            "surface_read": self._read,
            "surface_apply": self._apply,
            "surface_diff": self._diff,
            "surface_rollback": self._rollback,
            "eval_suites": self._suites,
            "eval_criteria": self._criteria,
            "eval_gold": self._gold,
            "eval_run": self._eval_run,
            "trace_query": self._trace_query,
            "trace_read": self._trace_read,
            "notes_read": self._notes_read,
            "notes_write": self._notes_write,
            "journal_read": self._journal_read,
            "finish_round": self._finish,
        }

    def start_round(self) -> None:
        self.surface.restore_accepted()
        self.round_start = self.surface.accepted()
        self.finished = False
        self.outcome = None
        self.last_eval = None
        prior = self.state.read_json("last-train.json")
        self.first_eval = (
            prior
            if prior
            and prior.get("version") == self.round_start
            and prior.get("complete")
            else None
        )

    def schemas(self) -> list[dict[str, Any]]:
        return evolve_tool_schemas()

    def dispatch(self, call: dict[str, Any]) -> dict[str, Any]:
        fn = call.get("function") or {}
        name = fn.get("name") or call.get("name")
        raw = fn.get("arguments") or call.get("arguments") or "{}"
        if isinstance(raw, dict):
            args = raw
        else:
            try:
                args = json.loads(raw) if raw else {}
            except json.JSONDecodeError as exc:
                return {
                    "role": "tool",
                    "tool_call_id": call.get("id") or name,
                    "content": _err(f"invalid JSON arguments: {exc.msg}"),
                }
        if not isinstance(args, dict):
            return {
                "role": "tool",
                "tool_call_id": call.get("id") or name,
                "content": _err("tool arguments must be a JSON object"),
            }
        handler = self._handlers.get(name or "")
        if handler is None:
            content = _err(f"unknown tool: {name}")
        else:
            try:
                content = handler(**args)
            except HiddenCase:
                content = _err(_UNAVAILABLE)
            except (SurfaceError, TypeError, KeyError, ValueError) as exc:
                content = _err(str(exc))
        return {
            "role": "tool",
            "tool_call_id": call.get("id") or name,
            "content": content,
        }

    def _resolve(self, version: str | None) -> str:
        if not version or version == "HEAD":
            return self.surface.head()
        if version == "BASE":
            return self.round_start
        return version

    def _manifest(self) -> str:
        return self.surface.manifest().model_dump_json(indent=2)

    def _read(self, unit_id: str) -> str:
        return _ok({"unit_id": unit_id, "content": self.surface.read(unit_id)})

    def _apply(self, unit_id: str, content: str) -> str:
        version = self.surface.apply(Change(unit_id=unit_id, content=content))
        self.last_eval = None
        return _ok({"version": version})

    def _diff(self, a: str, b: str) -> str:
        return self.surface.diff(self._resolve(a), self._resolve(b)) or "(empty)"

    def _rollback(self, to: str) -> str:
        version = self._resolve(to)
        self.surface.rollback(version)
        self.last_eval = None
        return _ok({"version": self.surface.head()})

    def _suites(self) -> str:
        return _ok([s.model_dump() for s in self.eval_port.suites()])

    def _criteria(self) -> str:
        return self.eval_port.criteria() or "(none)"

    def _gold(self, case_id: str) -> str:
        gold = self.eval_port.gold(case_id)
        return _ok({"case_id": case_id, "gold": gold})

    def _eval_run(self, case_ids: list[str] | None = None, version: str | None = None) -> str:
        resolved = self._resolve(version)
        requested = list(case_ids or self.eval_port.train_ids())
        result = self.eval_port.run(requested, resolved)
        expected = set(self.eval_port.train_ids())
        snapshot = eval_snapshot(result, resolved, requested, expected)
        if self.first_eval is None:
            self.first_eval = snapshot
        self.last_eval = snapshot
        self.state.write_json("last-train.json", snapshot)
        self.state.append(
            "eval",
            score=result.score,
            n=len(result.cases),
            passed=result.passed,
            passed_cases=snapshot["passed_cases"],
            version=snapshot["version"],
        )
        return result.model_dump_json(indent=2)

    def _trace_query(
        self,
        status: str | None = None,
        feedback_name: str | None = None,
        max_feedback_score: float | None = None,
        has_human_feedback: bool | None = None,
        limit: int = 20,
    ) -> str:
        refs = self.traces.query(
            TraceFilter(
                status=status,
                feedback_name=feedback_name,
                max_feedback_score=max_feedback_score,
                has_human_feedback=has_human_feedback,
                limit=limit,
            )
        )
        return _ok([r.model_dump(mode="json") for r in refs])

    def _trace_read(self, ref: str) -> str:
        for item in self.traces.query(TraceFilter(limit=1000)):
            if item.ref == ref:
                return self.traces.read(item).model_dump_json(indent=2)
        return _err("unknown trace")

    def _notes_read(self) -> str:
        return self.state.notes() or "(empty)"

    def _notes_write(self, content: str) -> str:
        self.state.write_notes(content)
        return _ok({"ok": True})

    def _journal_read(self) -> str:
        return _ok(self.state.journal())

    def _finish(
        self,
        decision: str,
        summary: str,
        argument: str,
        categories: list[str],
        evidence_refs: list[str],
        refactor: str,
    ) -> str:
        if decision not in {"accept", "reject"}:
            return _err("decision must be accept or reject")
        allowed_categories = {"knowledge", "experience", "tool", "process"}
        if not categories or not set(categories) <= allowed_categories:
            return _err("categories must contain one or more valid failure categories")
        known_refs = set(self.eval_port.train_ids())
        known_refs.update(ref.ref for ref in self.traces.query(TraceFilter(limit=1000)))
        unknown_refs = set(evidence_refs) - known_refs
        if unknown_refs:
            return _err("one or more evidence refs are unknown")
        if decision == "accept" and (not evidence_refs or not refactor.strip()):
            return _err("accepted rounds require evidence refs and a refactor account")
        train = {
            "before": None if not self.first_eval else self.first_eval.get("score"),
            "after": None if not self.last_eval else self.last_eval.get("score"),
        }
        if decision == "reject":
            self.surface.rollback(self.round_start)
            self.outcome = {
                "decision": "reject",
                "version": self.surface.head(),
                "summary": summary,
                "argument": argument,
                "categories": categories,
                "evidence_refs": evidence_refs,
                "refactor": refactor,
                "train": train,
            }
            self._persist_round(self.outcome)
            self.finished = True
            return _ok(self.outcome)
        current = self.surface.head()
        if self.last_eval is None:
            return _err("current candidate has not been evaluated")
        if self.last_eval.get("version") != current:
            return _err("train evidence is stale for the current candidate")
        if not self.last_eval.get("complete"):
            return _err("run the complete train suite before accepting")
        if not self.last_eval.get("passed"):
            return _err("the complete train suite is not green")
        report = self.gate.check(current)
        if not report["passed"]:
            return _ok(
                {
                    "accepted": False,
                    "gate": {
                        "passed": False,
                        "score": report["score"],
                        "baseline_score": report["baseline_score"],
                        "note": "holdout regressed; per-case details are not available",
                    },
                }
            )
        previous_accepted = self.surface.accepted()
        outcome = {
            "decision": "accept",
            "version": current,
            "summary": summary,
            "argument": argument,
            "categories": categories,
            "evidence_refs": evidence_refs,
            "refactor": refactor,
            "train": train,
            "gate_score": report["score"],
            "gate_baseline": report["baseline_score"],
        }
        try:
            with self.state.file_transaction(
                [
                    "gate-baseline.json",
                    "last-round.json",
                    "last-accepted.json",
                    "journal.jsonl",
                ]
            ):
                self.gate.commit(current)
                self._persist_round(outcome)
                accepted = self.surface.mark_accepted(current)
        except BaseException:
            self.surface.mark_accepted(previous_accepted)
            self.surface.restore_accepted()
            self.outcome = None
            raise
        outcome["version"] = accepted
        self.outcome = outcome
        self.finished = True
        return _ok(self.outcome)

    def _persist_round(self, outcome: dict[str, Any]) -> None:
        self.state.append("round_end", **outcome)
        self.state.write_json(
            "last-round.json",
            {
                **outcome,
                "eval_before": self.first_eval,
                "eval_after": self.last_eval,
            },
        )
        if outcome.get("decision") == "accept":
            self.state.write_json("last-accepted.json", {**outcome, "eval_before": self.first_eval, "eval_after": self.last_eval})
