from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
import yaml

from kochab.adapters.eval_cli import CliEvalPort
from kochab.adapters.eval_formats import EvalFormat
from kochab.adapters.files import FileSurface
from kochab.adapters.otel import OtelFileTracePort
from kochab.contracts.models import UnitManifest


class HostBinding(BaseModel):
    """Frozen files, evaluation command, and OTLP trace binding."""

    model_config = ConfigDict(extra="forbid")

    surface: SurfaceBinding
    eval: EvalBinding
    trace: TraceBinding
    gate: GateBinding


class SurfaceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    units: list[UnitManifest]


class EvalBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str]
    list_args: list[str] = Field(default_factory=lambda: ["--list"])
    run_args: list[str]
    criteria_path: str | None = None
    cases_path: str | None = None
    dependency_paths: list[str] = Field(default_factory=list)
    format: EvalFormat = "kochab"
    pass_threshold: float = 1.0
    result_path: str | None = None
    result_glob: str | None = None
    timeout_seconds: int = 120


class TraceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["otlp-json"] = "otlp-json"
    path: str


class GateBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    holdout_ids: list[str]


class BoundHost:
    def __init__(self, root: Path, binding: HostBinding) -> None:
        self.root = root
        self.binding = binding
        self.state_dir = root / ".kochab"
        self.surface = FileSurface(
            work_dir=self.state_dir / "work",
            units=list(binding.surface.units),
            source_root=root,
        )
        self.eval = CliEvalPort(
            host_root=root,
            command=binding.eval.command,
            list_args=binding.eval.list_args,
            run_args=binding.eval.run_args,
            surface=self.surface,
            criteria_path=binding.eval.criteria_path,
            cases_path=binding.eval.cases_path,
            format=binding.eval.format,
            pass_threshold=binding.eval.pass_threshold,
            result_path=binding.eval.result_path,
            result_glob=binding.eval.result_glob,
            timeout=binding.eval.timeout_seconds,
        )
        trace_path = (root / binding.trace.path).resolve()
        try:
            trace_path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError("trace path escapes host root") from exc
        self.traces = OtelFileTracePort(trace_path)
        self.holdout_ids = set(binding.gate.holdout_ids)

    def prepare(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.surface.bootstrap()
        if not self.holdout_ids:
            raise ValueError("holdout gate must contain at least one case")
        unknown = self.holdout_ids - self.eval.known_ids()
        if unknown:
            raise ValueError(f"holdout ids not in eval suite: {sorted(unknown)}")
        if not (self.eval.known_ids() - self.holdout_ids):
            raise ValueError("eval suite must contain at least one train case")


def load_host(host_dir: Path) -> BoundHost:
    path = host_dir / "kochab-host.yaml"
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return BoundHost(host_dir, HostBinding.model_validate(data))
