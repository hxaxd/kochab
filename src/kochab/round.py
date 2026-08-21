from __future__ import annotations

import json
from typing import Any

from kochab.core.loop import LoopResult, run
from kochab.prompts import evolve_prompt
from kochab.session import Session


def opening_brief(session: Session) -> str:
    """Human+model facing context for this round. Must not mention holdout ids."""
    train_n = len(session.gated_eval.suites())
    last_train = session.state.read_json("last-train.json")
    last_round = session.state.read_json("last-round.json")
    journal = session.state.journal(limit=8)
    score_line = "none yet"
    if last_train:
        score_line = (
            f"{last_train.get('score')} "
            f"({last_train.get('passed_cases')}/{last_train.get('n')} cases passed; "
            f"suite_passed={last_train.get('passed')})"
        )
    decision = (last_round or {}).get("decision") or "none"
    notes = "present" if session.state.notes() else "empty"
    journal_preview = json.dumps(journal, ensure_ascii=False, indent=2) if journal else "[]"
    return (
        "Run one evolution round on this host.\n"
        f"Work-copy version: {session.host.surface.head()}\n"
        f"Train cases: {train_n}\n"
        f"Last recorded train score: {score_line}\n"
        f"Last round decision: {decision}\n"
        f"Notes: {notes}\n"
        "Start by reading the surface and the train suite. "
        "If a journal already exists, this is not the first round.\n\n"
        f"Recent journal:\n{journal_preview}"
    )


def execute_round(
    session: Session,
    llm: Any,
    max_steps: int = 40,
    on_event: Any = None,
) -> LoopResult:
    session.tools.start_round()
    messages = [
        {"role": "system", "content": evolve_prompt()},
        {"role": "user", "content": opening_brief(session)},
    ]
    try:
        result = run(llm, session.tools, messages, max_steps=max_steps, on_event=on_event)
    except KeyboardInterrupt:
        session.host.surface.restore_accepted()
        session.state.save_round(
            messages,
            None,
            status="interrupted",
            reason="keyboard_interrupt",
        )
        raise
    decision = (result.outcome or {}).get("decision")
    if decision in {"accept", "reject"}:
        status = "accepted" if decision == "accept" else "rejected"
    else:
        status = "failed"
        session.host.surface.restore_accepted()
    session.state.save_round(
        result.messages,
        result.outcome,
        status=status,
        reason=result.reason,
        error=result.error,
    )
    if not result.outcome:
        session.state.write_json(
            "last-round.json",
            {
                "decision": None,
                "status": status,
                "reason": result.reason,
                "error": result.error,
                "version": session.host.surface.accepted(),
            },
        )
    return result
