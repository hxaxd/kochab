from __future__ import annotations

import json
from pathlib import Path

from kochab.core.llm import ScriptedLLM
from kochab.discovery import DiscoveryTools, discover_host


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


def test_discovery_writes_a_validated_draft(tmp_path: Path) -> None:
    (tmp_path / "SYSTEM.md").write_text("prompt", encoding="utf-8")
    binding = """surface:
  units:
    - id: system
      category: knowledge
      path: SYSTEM.md
eval:
  command: ["{python}", "eval.py"]
  run_args: ["--surface", "{surface_dir}", "--cases", "{case_ids}"]
trace:
  kind: otlp-json
  path: traces/otel.jsonl
gate:
  holdout_ids: [hidden-1]
"""
    result = discover_host(
        tmp_path,
        ScriptedLLM(
            [
                _call("repo_list", path=""),
                _call(
                    "finish_discovery",
                    binding_yaml=binding,
                    rationale="one prompt and one evaluator",
                    unresolved=["confirm the holdout choice"],
                ),
            ]
        ),
    )
    assert result.outcome
    assert (tmp_path / "kochab-host.draft.yaml").exists()
    assert "confirm the holdout" in (tmp_path / "kochab-host.draft.yaml.md").read_text(encoding="utf-8")


def test_discovery_tools_cannot_escape_host(tmp_path: Path) -> None:
    tools = DiscoveryTools(tmp_path)
    result = tools.dispatch(_call("repo_read", path="../secret.txt")["tool_calls"][0])
    assert "escapes repository" in result["content"]
