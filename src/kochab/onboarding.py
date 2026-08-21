from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from kochab.adapters.host import BoundHost, load_host
from kochab.contracts.models import TraceFilter
from kochab.core.eval_snapshot import eval_snapshot
from kochab.session import Session

SEAL_SCHEMA = 2
SEAL_NAME = "binding.lock.json"


class FrozenBindingError(RuntimeError):
    pass


class OnboardingReport(BaseModel):
    ready: bool
    frozen: bool
    surface_units: list[str]
    train_cases: int
    train_score: float
    train_passed: bool
    holdout_cases: int
    trace_probe: str
    state_backup: str | None = None
    warnings: list[str] = Field(default_factory=list)


def onboard_host(
    host_dir: Path, *, freeze: bool = False, reset_state: bool = False
) -> OnboardingReport:
    backup = _reset_state(host_dir) if reset_state else None
    host = load_host(host_dir)
    _reject_surface_rebind(host)
    host.prepare()
    session = Session(host)
    manifest = host.surface.manifest()
    for unit in manifest.units:
        host.surface.read(unit.id)
    train_ids = session.gated_eval.train_ids()
    version = host.surface.head()
    train = session.gated_eval.run(train_ids, version, visibility="train")
    session.state.write_json(
        "last-train.json",
        eval_snapshot(train, version, train_ids, set(train_ids)),
    )
    session.gate.capture_if_missing(host.surface.head())
    refs = host.traces.query(TraceFilter(limit=1))
    trace_probe = "empty"
    warnings: list[str] = []
    if refs:
        host.traces.read(refs[0])
        trace_probe = "readable"
    else:
        warnings.append("trace source is valid but currently empty")
    report = OnboardingReport(
        ready=True,
        frozen=freeze,
        surface_units=[unit.id for unit in manifest.units],
        train_cases=len(train_ids),
        train_score=train.score,
        train_passed=train.passed,
        holdout_cases=len(host.holdout_ids),
        trace_probe=trace_probe,
        state_backup=str(backup) if backup else None,
        warnings=warnings,
    )
    session.state.write_json("onboarding-report.json", report.model_dump())
    if freeze:
        session.state.write_json(SEAL_NAME, _seal(host))
    return report


def verify_frozen(host: BoundHost) -> None:
    path = host.state_dir / SEAL_NAME
    if not path.exists():
        raise FrozenBindingError(
            f"host is not frozen; run `kochab onboard {host.root} --freeze` first"
        )
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FrozenBindingError(f"cannot read frozen binding seal: {exc}") from exc
    expected = _seal(host, captured_at=actual.get("captured_at"))
    mismatches = [
        key
        for key in (
            "schema",
            "binding_sha256",
            "surface",
            "criteria_sha256",
            "eval_dependencies",
            "case_catalog",
        )
        if actual.get(key) != expected.get(key)
    ]
    if mismatches:
        raise FrozenBindingError(
            "frozen host inputs changed: "
            + ", ".join(mismatches)
            + "; run onboarding again (use --reset-state when surface source files changed)"
        )


def _seal(host: BoundHost, captured_at: str | None = None) -> dict[str, Any]:
    binding_path = host.root / "kochab-host.yaml"
    surface = _surface_seal(host)
    criteria_sha = None
    if host.binding.eval.criteria_path:
        path = host.root / host.binding.eval.criteria_path
        criteria_sha = _hash_file(path) if path.exists() else None
    catalog = [
        {
            "id": item.id,
            "label": item.label,
            "question": item.question,
            "gold_sha256": _hash_text(host.eval.gold(item.id) or ""),
        }
        for item in host.eval.suites()
    ]
    return {
        "schema": SEAL_SCHEMA,
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "binding_sha256": _hash_file(binding_path),
        "surface": surface,
        "criteria_sha256": criteria_sha,
        "eval_dependencies": _eval_dependencies(host),
        "case_catalog": sorted(catalog, key=lambda item: item["id"]),
    }


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _eval_dependencies(host: BoundHost) -> list[dict[str, str]]:
    tokens = [
        *host.binding.eval.command,
        *host.binding.eval.list_args,
        *host.binding.eval.run_args,
    ]
    explicit = list(host.binding.eval.dependency_paths)
    if host.binding.eval.cases_path:
        explicit.append(host.binding.eval.cases_path)
    dependencies: list[dict[str, str]] = []
    seen: set[Path] = set()

    def add_file(candidate: Path, display: str) -> None:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(host.root.resolve())
        except ValueError as exc:
            raise FrozenBindingError(f"eval dependency escapes host root: {display}") from exc
        if resolved in seen:
            return
        seen.add(resolved)
        dependencies.append(
            {
                "path": resolved.relative_to(host.root.resolve()).as_posix(),
                "sha256": _hash_file(resolved),
            }
        )

    for token in tokens:
        token_path = Path(token)
        if "{" in token or token_path.is_absolute():
            continue
        candidate = host.root / token
        if candidate.is_file():
            add_file(candidate, token)
    for raw in explicit:
        candidate = (host.root / raw).resolve()
        try:
            candidate.relative_to(host.root.resolve())
        except ValueError as exc:
            raise FrozenBindingError(f"eval dependency escapes host root: {raw}") from exc
        if not candidate.exists():
            raise FrozenBindingError(f"eval dependency does not exist: {raw}")
        if candidate.is_file():
            add_file(candidate, raw)
            continue
        for item in sorted(candidate.rglob("*")):
            if item.is_file():
                add_file(item, raw)
    return sorted(dependencies, key=lambda item: item["path"])


def _surface_seal(host: BoundHost) -> list[dict[str, str]]:
    return [
        {
            "id": unit.id,
            "path": unit.path,
            "sha256": _hash_file(host.root / unit.path),
        }
        for unit in host.binding.surface.units
    ]


def _reject_surface_rebind(host: BoundHost) -> None:
    seal_path = host.state_dir / SEAL_NAME
    if not seal_path.exists():
        return
    try:
        previous = json.loads(seal_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if previous.get("surface") != _surface_seal(host):
        raise FrozenBindingError(
            "surface source files changed; rerun onboarding with --reset-state "
            "to start a fresh work copy while preserving a backup"
        )


def _reset_state(host_dir: Path) -> Path | None:
    state_dir = host_dir / ".kochab"
    if not state_dir.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = host_dir / f".kochab.backup-{stamp}-{uuid.uuid4().hex[:8]}"
    state_dir.rename(backup)
    return backup
