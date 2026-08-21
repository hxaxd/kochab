from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from kochab.contracts.models import Trace, TraceFilter
from kochab.core.loop import LoopResult
from kochab.locking import HostLock
from kochab.otlp_receiver import OtlpFileSink, serve_in_thread
from kochab.round import execute_round
from kochab.session import open_session


def run_daemon(
    host_dir: Path,
    llm_factory: Callable[[], Any],
    *,
    once: bool = False,
    poll_seconds: float = 5.0,
    max_steps: int = 40,
    on_event: Any = None,
    otlp_host: str | None = None,
    otlp_port: int = 4318,
) -> list[LoopResult]:
    """Watch standardized traces and let the evolution model judge new evidence."""
    results: list[LoopResult] = []
    probe = open_session(host_dir, require_frozen=True)
    receiver = (
        serve_in_thread(OtlpFileSink(probe.host.traces.path), otlp_host, otlp_port)
        if otlp_host
        else nullcontext()
    )
    with receiver:
        while True:
            session = open_session(host_dir, require_frozen=True)
            with HostLock(session.state.dir):
                cursor = session.state.read_json("trace-cursor.json") or {"seen": []}
                seen_order = list(cursor.get("seen") or [])
                seen = set(seen_order)
                refs = session.host.traces.query(TraceFilter(limit=1000))
                pending = [ref for ref in reversed(refs) if ref.ref not in seen]
                relevant = []
                for ref in pending:
                    trace = session.host.traces.read(ref)
                    if _is_evidence(trace):
                        relevant.append(ref)
                if relevant:
                    session.state.append(
                        "daemon_trigger",
                        traces=[ref.ref for ref in relevant],
                        observed=len(pending),
                    )
                    result = execute_round(
                        session,
                        llm_factory(),
                        max_steps=max_steps,
                        on_event=on_event,
                    )
                    results.append(result)
                    if result.reason != "error":
                        _mark_seen(seen, seen_order, pending)
                else:
                    _mark_seen(seen, seen_order, pending)
                session.state.write_json("trace-cursor.json", {"seen": seen_order[-10000:]})
            if once:
                return results
            time.sleep(max(0.1, poll_seconds))


def _is_evidence(trace: Trace) -> bool:
    if trace.resource.get("kochab.eval.visibility") in {"train", "holdout"}:
        return False
    if trace.status == "error" or trace.human_feedback:
        return True
    return bool(trace.feedback)


def _mark_seen(seen: set[str], order: list[str], refs: list[Any]) -> None:
    for ref in refs:
        if ref.ref not in seen:
            seen.add(ref.ref)
            order.append(ref.ref)
