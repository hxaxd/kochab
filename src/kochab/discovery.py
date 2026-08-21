from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

import yaml

from kochab.adapters.host import HostBinding
from kochab.core.loop import LoopResult, run

DISCOVERY_PROMPT = """You are onboarding an arbitrary agent host into kochab.

Inspect the repository read-only. Identify:
- the smallest files/configuration that are safe and useful to tune;
- a deterministic evaluation command and a case catalog;
- a non-empty train set and a small hidden holdout set;
- an OTLP JSON/JSONL trace file. Prefer OpenTelemetry GenAI semantic conventions and
  accept OpenInference attributes carried by OTLP.

Do not invent paths or commands. If evidence is missing, record a concrete unresolved
question. Finish by calling finish_discovery with a kochab-host.yaml draft. The draft
schema is:

surface:
  units: [{id, category: knowledge|experience|tool|process, path, format, max_bytes?}]
eval:
  command: [executable, ...]
  list_args: [...]
  run_args: [..., "{surface_dir}", "{case_ids}", "{result_path}"]
  criteria_path: optional/path
  cases_path: optional/path.json
  dependency_paths: [evaluation scripts, rubrics, datasets, or dependency directories]
  format: kochab|jsonl|promptfoo|junit|inspect
  pass_threshold: 1.0
  result_path: optional-relative-result-file
  result_glob: optional-glob-under-{result_dir}
  timeout_seconds: 120
trace:
  kind: otlp-json
  path: traces/otel.jsonl
gate:
  holdout_ids: [non-empty ids from the case catalog]

Use {python} in command arrays for the active Python interpreter. Never include API
keys, tokens, production writes, deployment commands, or shell pipelines.

Runtime facts you should not list as unresolved questions:
- when result_path/result_glob is absent, kochab parses evaluator stdout;
- train subprocesses receive KOCHAB_EVAL_VISIBILITY=train;
- holdout subprocesses receive KOCHAB_EVAL_VISIBILITY=holdout and disable standard
  OpenTelemetry export;
- dependency_paths should include local modules, rubrics, and datasets used by eval.
"""


class DiscoveryTools:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.finished = False
        self.outcome: dict[str, Any] | None = None
        self._handlers: dict[str, Callable[..., str]] = {
            "repo_list": self._list,
            "repo_read": self._read,
            "repo_search": self._search,
            "finish_discovery": self._finish,
        }

    def schemas(self) -> list[dict[str, Any]]:
        return [
            _fn("repo_list", "List repository files, optionally under one directory.", {"path": _str("Relative directory; empty means root.")}),
            _fn("repo_read", "Read a UTF-8 text file.", {"path": _str("Relative file path.")}, ["path"]),
            _fn(
                "repo_search",
                "Regex search across small UTF-8 repository files.",
                {"pattern": _str("Regular expression."), "path": _str("Optional relative directory.")},
                ["pattern"],
            ),
            _fn(
                "finish_discovery",
                "Return a validated binding draft and the remaining human questions.",
                {
                    "binding_yaml": _str("Raw YAML matching the documented schema."),
                    "rationale": _str("Why each port and tuning unit was selected."),
                    "unresolved": {"type": "array", "items": {"type": "string"}},
                },
                ["binding_yaml", "rationale", "unresolved"],
            ),
        ]

    def dispatch(self, call: dict[str, Any]) -> dict[str, Any]:
        fn = call.get("function") or {}
        name = str(fn.get("name") or "")
        try:
            args = json.loads(fn.get("arguments") or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
            handler = self._handlers.get(name)
            if handler is None:
                raise ValueError(f"unknown tool: {name}")
            content = handler(**args)
        except (ValueError, TypeError, OSError, yaml.YAMLError) as exc:
            content = json.dumps({"error": str(exc)}, ensure_ascii=False)
        return {"role": "tool", "tool_call_id": call.get("id") or name, "content": content}

    def _list(self, path: str = "") -> str:
        base = self._path(path or ".", directory=True)
        files = []
        for item in base.rglob("*"):
            if not item.is_file() or self._ignored(item):
                continue
            files.append(item.relative_to(self.root).as_posix())
            if len(files) >= 500:
                break
        return json.dumps(files, ensure_ascii=False, indent=2)

    def _read(self, path: str) -> str:
        target = self._path(path)
        if target.stat().st_size > 256 * 1024:
            raise ValueError("file exceeds 256 KiB discovery read limit")
        return target.read_text(encoding="utf-8")

    def _search(self, pattern: str, path: str = "") -> str:
        regex = re.compile(pattern)
        base = self._path(path or ".", directory=True)
        matches = []
        for item in base.rglob("*"):
            if not item.is_file() or self._ignored(item) or item.stat().st_size > 256 * 1024:
                continue
            try:
                lines = item.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(lines, 1):
                if regex.search(line):
                    matches.append(
                        {"path": item.relative_to(self.root).as_posix(), "line": number, "text": line[:500]}
                    )
                    if len(matches) >= 200:
                        return json.dumps(matches, ensure_ascii=False, indent=2)
        return json.dumps(matches, ensure_ascii=False, indent=2)

    def _finish(self, binding_yaml: str, rationale: str, unresolved: list[str]) -> str:
        if not isinstance(unresolved, list) or any(not isinstance(item, str) for item in unresolved):
            raise ValueError("unresolved must be an array of question strings")
        data = yaml.safe_load(binding_yaml)
        binding = HostBinding.model_validate(data)
        normalized = yaml.safe_dump(
            binding.model_dump(exclude_none=True, exclude_defaults=True),
            sort_keys=False,
            allow_unicode=True,
        )
        self.outcome = {
            "binding_yaml": normalized,
            "rationale": rationale,
            "unresolved": list(unresolved),
        }
        self.finished = True
        return json.dumps({"accepted": True, "unresolved": unresolved}, ensure_ascii=False)

    def _path(self, path: str, directory: bool = False) -> Path:
        target = (self.root / path).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("path escapes repository") from exc
        if not target.exists():
            raise ValueError(f"path does not exist: {path}")
        if directory and not target.is_dir():
            raise ValueError(f"not a directory: {path}")
        if not directory and not target.is_file():
            raise ValueError(f"not a file: {path}")
        return target

    def _ignored(self, path: Path) -> bool:
        parts = set(path.relative_to(self.root).parts)
        return bool(parts & {".git", ".kochab", "node_modules", "__pycache__", ".venv", "venv"})


def discover_host(
    host_dir: Path,
    llm: Any,
    *,
    out: Path | None = None,
    max_steps: int = 30,
    on_event: Any = None,
) -> LoopResult:
    tools = DiscoveryTools(host_dir)
    result = run(
        llm,
        tools,
        [
            {"role": "system", "content": DISCOVERY_PROMPT},
            {"role": "user", "content": "Discover this host and produce its frozen-contract draft."},
        ],
        max_steps=max_steps,
        on_event=on_event,
    )
    if result.outcome:
        target = out or host_dir / "kochab-host.draft.yaml"
        target.write_text(result.outcome["binding_yaml"], encoding="utf-8")
        report = target.with_suffix(target.suffix + ".md")
        questions = "\n".join(f"- {item}" for item in result.outcome["unresolved"]) or "- None"
        report.write_text(
            f"# kochab discovery\n\n{result.outcome['rationale']}\n\n## Unresolved\n\n{questions}\n",
            encoding="utf-8",
        )
    return result


def _str(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _fn(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        },
    }
