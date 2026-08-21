from __future__ import annotations

import json
from pathlib import Path

from kochab.contracts.models import Change
from kochab.core.llm import ScriptedLLM
from kochab.export import export_pack
from kochab.round import execute_round
from kochab.session import open_session
from helpers import GENERAL_SYSTEM, STUFFED_SYSTEM, copy_toy


def _call(name: str, **args: object) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": name,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


def test_scripted_round_accepts_general_policies(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    session = open_session(host)
    llm = ScriptedLLM(
        [
            _call("surface_manifest"),
            _call("eval_run", case_ids=[]),
            _call("surface_apply", unit_id="system", content=GENERAL_SYSTEM),
            _call("eval_run", case_ids=[]),
            _call(
                "finish_round",
                decision="accept",
                summary="Filled standing policies.",
                argument="Train failures were missing policy facts; wrote general bullets.",
                categories=["knowledge"],
                evidence_refs=["tr_loan"],
                refactor="Generalized case answers into standing policies.",
            ),
        ]
    )
    result = execute_round(session, llm)
    assert result.reason == "finished"
    assert result.outcome and result.outcome["decision"] == "accept"
    assert "21 days" in session.host.surface.read("system")
    leaked = "\n".join(
        msg.get("content") or ""
        for msg in result.messages
        if msg.get("role") in {"tool", "user", "system"}
    )
    assert "ho_loan" not in leaked
    pack = export_pack(host, tmp_path / "pack")
    assert "21 days" in (pack / "surface.diff").read_text(encoding="utf-8")
    meta = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
    assert meta["decision"] == "accept"
    assert meta["train"]["after"] == 1.0
    after = json.loads((pack / "train-after.json").read_text(encoding="utf-8"))
    assert after["score"] == 1.0
    gate = json.loads((pack / "gate.json").read_text(encoding="utf-8"))
    assert gate["passed"] is True
    evidence = json.loads((pack / "evidence.json").read_text(encoding="utf-8"))
    assert evidence == {"categories": ["knowledge"], "refs": ["tr_loan"]}
    assert list((session.state.dir / "rounds").glob("*.json"))


def test_scripted_round_rejects_stuffed_faq(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    session = open_session(host)
    general = session.host.surface.apply(Change(unit_id="system", content=GENERAL_SYSTEM))
    # Ratchet a strong baseline, then try to accept a stuffed FAQ.
    assert session.gate.check(general)["passed"]
    session.host.surface.mark_accepted(general)
    session.gate.commit(general)
    llm = ScriptedLLM(
        [
            _call("surface_apply", unit_id="system", content=STUFFED_SYSTEM),
            _call("eval_run", case_ids=[]),
            _call(
                "finish_round",
                decision="accept",
                summary="Memorized train questions.",
                argument="Stuffed FAQ.",
                categories=["knowledge"],
                evidence_refs=["tr_loan"],
                refactor="No useful refactor.",
            ),
        ]
    )
    result = execute_round(session, llm, max_steps=8)
    # Gate failure is returned as a tool result; the script then ends with no_tools.
    tool_texts = [
        msg.get("content") or ""
        for msg in result.messages
        if msg.get("role") == "tool"
    ]
    assert any("holdout regressed" in text for text in tool_texts)
    assert result.outcome is None
    assert session.host.surface.head() == general
    assert session.host.surface.accepted() == general


def test_unfinished_round_restores_accepted_version(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    session = open_session(host)
    accepted = session.host.surface.accepted()
    result = execute_round(
        session,
        ScriptedLLM([_call("surface_apply", unit_id="system", content="candidate\n")]),
        max_steps=4,
    )
    assert result.reason == "no_tools"
    assert result.outcome is None
    assert session.host.surface.head() == accepted
    assert session.host.surface.read("system") != "candidate\n"


def test_accept_rejects_stale_train_evidence(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    session = open_session(host)
    result = execute_round(
        session,
        ScriptedLLM(
            [
                _call("eval_run", case_ids=[]),
                _call("surface_apply", unit_id="system", content=GENERAL_SYSTEM),
                _call(
                    "finish_round",
                    decision="accept",
                    summary="stale",
                    argument="stale",
                    categories=["knowledge"],
                    evidence_refs=["tr_loan"],
                    refactor="stale",
                ),
            ]
        ),
    )
    assert result.outcome is None
    errors = [m["content"] for m in result.messages if m.get("role") == "tool"]
    assert any("has not been evaluated" in item for item in errors)


def test_accept_rejects_partial_train_evidence(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    session = open_session(host)
    result = execute_round(
        session,
        ScriptedLLM(
            [
                _call("surface_apply", unit_id="system", content=GENERAL_SYSTEM),
                _call("eval_run", case_ids=["tr_loan"]),
                _call(
                    "finish_round",
                    decision="accept",
                    summary="partial",
                    argument="partial",
                    categories=["knowledge"],
                    evidence_refs=["tr_loan"],
                    refactor="partial",
                ),
            ]
        ),
    )
    assert result.outcome is None
    errors = [m["content"] for m in result.messages if m.get("role") == "tool"]
    assert any("complete train suite" in item for item in errors)


def test_accept_transaction_rolls_back_gate_and_candidate_on_state_failure(
    tmp_path: Path, monkeypatch
) -> None:
    host = copy_toy(tmp_path)
    session = open_session(host)
    accepted = session.host.surface.accepted()
    gate_before = (session.state.dir / "gate-baseline.json").read_bytes()

    def fail_persist(outcome: dict) -> None:
        raise RuntimeError("injected state failure")

    monkeypatch.setattr(session.tools, "_persist_round", fail_persist)
    result = execute_round(
        session,
        ScriptedLLM(
            [
                _call("surface_apply", unit_id="system", content=GENERAL_SYSTEM),
                _call("eval_run", case_ids=[]),
                _call(
                    "finish_round",
                    decision="accept",
                    summary="candidate",
                    argument="candidate",
                    categories=["knowledge"],
                    evidence_refs=["tr_loan"],
                    refactor="generalized policy",
                ),
            ]
        ),
    )
    assert result.reason == "error"
    assert session.host.surface.accepted() == accepted
    assert session.host.surface.head() == accepted
    assert (session.state.dir / "gate-baseline.json").read_bytes() == gate_before
    assert session.state.read_json("last-accepted.json") is None


def test_failed_later_round_does_not_replace_exported_acceptance(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    session = open_session(host)
    accepted = execute_round(
        session,
        ScriptedLLM(
            [
                _call("surface_apply", unit_id="system", content=GENERAL_SYSTEM),
                _call("eval_run", case_ids=[]),
                _call(
                    "finish_round",
                    decision="accept",
                    summary="accepted policy",
                    argument="all checks passed",
                    categories=["knowledge"],
                    evidence_refs=["tr_loan"],
                    refactor="generalized policy",
                ),
            ]
        ),
    )
    assert accepted.outcome
    accepted_version = session.host.surface.accepted()

    failed = execute_round(
        session,
        ScriptedLLM([_call("surface_apply", unit_id="system", content="broken\n")]),
    )
    assert failed.outcome is None
    assert session.host.surface.accepted() == accepted_version
    pack = export_pack(host, tmp_path / "stable-pack")
    meta = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
    assert meta["version"] == accepted_version
    assert meta["decision"] == "accept"
    assert "21 days" in (pack / "surface.diff").read_text(encoding="utf-8")
