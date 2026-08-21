from __future__ import annotations

import json
from pathlib import Path

from helpers import GENERAL_SYSTEM, copy_toy
from kochab.core.llm import ScriptedLLM
from kochab.daemon import run_daemon
from kochab.export import export_pack
from kochab.onboarding import onboard_host


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


def test_onboarding_daemon_evolution_and_export_form_a_closed_loop(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    assert onboard_host(host, freeze=True).ready
    production_failure = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "toy-production"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "a" * 32,
                                "spanId": "b" * 16,
                                "name": "invoke_agent desk",
                                "attributes": [
                                    {"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}}
                                ],
                                "events": [
                                    {
                                        "name": "gen_ai.evaluation.result",
                                        "attributes": [
                                            {"key": "gen_ai.evaluation.name", "value": {"stringValue": "user_quality"}},
                                            {"key": "gen_ai.evaluation.score", "value": {"doubleValue": 0.0}},
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }
    with (host / "traces" / "otel.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(production_failure) + "\n")

    def llm_factory() -> ScriptedLLM:
        return ScriptedLLM(
            [
                _call("surface_apply", unit_id="system", content=GENERAL_SYSTEM),
                _call("eval_run", case_ids=[]),
                _call(
                    "finish_round",
                    decision="accept",
                    summary="Filled general policies from failed evidence.",
                    argument="The frozen baseline traces and train cases showed missing knowledge.",
                    categories=["knowledge"],
                    evidence_refs=["tr_loan"],
                    refactor="Consolidated case facts into reusable standing policies.",
                ),
            ]
        )

    results = run_daemon(host, llm_factory, once=True, otlp_host=None)
    assert len(results) == 1
    assert results[0].outcome and results[0].outcome["decision"] == "accept"

    pack = export_pack(host, tmp_path / "pack", require_frozen=True)
    assert "21 days" in (pack / "surface.diff").read_text(encoding="utf-8")
    assert json.loads((pack / "gate.json").read_text(encoding="utf-8"))["passed"] is True
    meta = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
    assert meta["train"] == {"before": 0.0, "after": 1.0}
