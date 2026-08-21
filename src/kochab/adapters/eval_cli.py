from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path
from typing import Any

from kochab.adapters.files import FileSurface
from kochab.adapters.eval_formats import EvalFormat, EvalFormatError, parse_eval_output
from kochab.contracts.models import EvalResult, SuiteInfo, Version


class EvalCliError(RuntimeError):
    pass


class CliEvalPort:
    """EvalPort: shell command in, JSON {score, cases:[{id,score,feedback}]} out."""

    def __init__(
        self,
        host_root: Path,
        command: list[str],
        list_args: list[str],
        run_args: list[str],
        surface: FileSurface,
        criteria_path: str | None = None,
        cases_path: str | None = None,
        format: EvalFormat = "kochab",
        pass_threshold: float = 1.0,
        result_path: str | None = None,
        result_glob: str | None = None,
        timeout: int = 120,
    ) -> None:
        self.host_root = host_root
        self.command = command
        self.list_args = list_args
        self.run_args = run_args
        self.surface = surface
        self.criteria_path = criteria_path
        self.cases_path = cases_path
        self.format = format
        self.pass_threshold = pass_threshold
        self.result_path = result_path
        self.result_glob = result_glob
        self.timeout = timeout
        self._listed: list[dict[str, Any]] | None = None

    def suites(self) -> list[SuiteInfo]:
        return [
            SuiteInfo(
                id=row["id"],
                label=row.get("label") or row["id"],
                question=row.get("question") or "",
            )
            for row in self._list()
        ]

    def criteria(self) -> str:
        if not self.criteria_path:
            return ""
        path = self._safe_path(self.host_root, self.criteria_path)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def gold(self, case_id: str) -> str | None:
        for row in self._list():
            if row["id"] == case_id:
                gold = row.get("gold")
                return str(gold) if gold else None
        return None

    def run(
        self,
        case_ids: list[str],
        surface_version: Version,
        visibility: str = "train",
    ) -> EvalResult:
        try:
            with self.surface.materialize(surface_version) as surface_dir:
                result_path = self._safe_path(
                    surface_dir, self.result_path or ".kochab-eval-output"
                )
                result_dir = surface_dir / ".kochab-eval-results"
                result_dir.mkdir(parents=True, exist_ok=True)
                args = [
                    self._subst(
                        part,
                        surface_dir=str(surface_dir),
                        case_ids=",".join(case_ids),
                        result_path=str(result_path),
                        result_dir=str(result_dir),
                    )
                    for part in self.run_args
                ]
                eval_env = {"KOCHAB_EVAL_VISIBILITY": visibility}
                resource = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
                marker = f"kochab.eval.visibility={visibility}"
                eval_env["OTEL_RESOURCE_ATTRIBUTES"] = f"{resource},{marker}".strip(",")
                if visibility == "holdout":
                    eval_env.update({"OTEL_SDK_DISABLED": "true", "OTEL_TRACES_EXPORTER": "none"})
                stdout = self._invoke(self.command + args, extra_env=eval_env)
                payload = self._result_payload(result_path, result_dir, stdout)
                return parse_eval_output(payload, self.format, self.pass_threshold)
        except EvalFormatError as exc:
            raise EvalCliError(str(exc)) from exc

    def known_ids(self) -> set[str]:
        return {row["id"] for row in self._list()}

    def _list(self) -> list[dict[str, Any]]:
        if self._listed is None:
            if self.cases_path:
                path = self._safe_path(self.host_root, self.cases_path)
                payload = path.read_text(encoding="utf-8")
            else:
                payload = self._invoke(self.command + self.list_args)
            try:
                import json

                data = json.loads(payload)
            except (OSError, ValueError) as exc:
                raise EvalCliError(f"invalid eval case catalog: {exc}") from exc
            self._listed = data if isinstance(data, list) else data["cases"]
        return self._listed

    def _invoke(self, argv: list[str], extra_env: dict[str, str] | None = None) -> str:
        argv = [self._subst(part) for part in argv]
        env = os.environ.copy()
        env.update(extra_env or {})
        try:
            proc = subprocess.run(
                argv,
                cwd=self.host_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise EvalCliError(f"eval command timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            raise EvalCliError(
                (proc.stderr or proc.stdout or "eval command failed").strip()
            )
        return proc.stdout.strip()

    def _result_payload(self, result_path: Path, result_dir: Path, stdout: str) -> str:
        if self.result_path:
            target = result_path
        elif self.result_glob:
            pattern = Path(self.result_glob)
            if pattern.is_absolute() or ".." in pattern.parts:
                raise EvalCliError("result_glob must stay under result_dir")
            matches = sorted(
                result_dir.glob(self.result_glob),
                key=lambda item: item.stat().st_mtime_ns,
                reverse=True,
            )
            if not matches:
                raise EvalCliError(f"eval produced no result matching {self.result_glob}")
            target = matches[0]
        else:
            return stdout
        if target.suffix == ".eval":
            try:
                from inspect_ai.log import read_eval_log
            except ImportError as exc:
                raise EvalCliError(
                    "reading Inspect .eval logs requires the host's inspect-ai package"
                ) from exc
            return read_eval_log(target).model_dump_json()
        try:
            return target.read_text(encoding="utf-8")
        except OSError as exc:
            raise EvalCliError(f"cannot read eval result {target}: {exc}") from exc

    @staticmethod
    def _safe_path(root: Path, relative: str) -> Path:
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise EvalCliError(f"path escapes allowed root: {relative}") from exc
        return target

    def _subst(self, part: str, **extra: str) -> str:
        mapping = {"python": sys.executable, **extra}
        out = part
        for key, value in mapping.items():
            out = out.replace("{" + key + "}", value)
        return out
