from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from kochab.contracts.models import (
    Change,
    SurfaceManifest,
    UnitManifest,
    Version,
)


class SurfaceError(RuntimeError):
    pass


class FileSurface:
    """TuningSurface over a git work copy of host files."""

    BASELINE_REF = "refs/kochab/baseline"
    ACCEPTED_REF = "refs/kochab/accepted"

    def __init__(
        self,
        work_dir: Path,
        units: list[UnitManifest],
        source_root: Path,
    ) -> None:
        self.work_dir = work_dir
        self.source_root = source_root
        self._units = {u.id: u for u in units}

    def bootstrap(self) -> Version:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        if not (self.work_dir / ".git").exists():
            self._git("init")
            self._git("config", "user.email", "kochab@local")
            self._git("config", "user.name", "kochab")
            for unit in self._units.values():
                self._copy_from_source(unit)
            self._git("add", "-A")
            self._git("-c", "commit.gpgsign=false", "commit", "-m", "kochab baseline", "--allow-empty")
        self._ensure_ref(self.BASELINE_REF, self._root_commit())
        self._ensure_ref(self.ACCEPTED_REF, self.head())
        return self.head()

    def head(self) -> Version:
        return self._git("rev-parse", "HEAD").strip()

    def manifest(self) -> SurfaceManifest:
        units = []
        for unit in self._units.values():
            text = self.read(unit.id)
            units.append(
                unit.model_copy(
                    update={"fingerprint": hashlib.sha256(text.encode()).hexdigest()[:12]}
                )
            )
        return SurfaceManifest(units=units, version=self.head())

    def read(self, unit_id: str) -> str:
        path = self._unit_path(unit_id)
        return path.read_text(encoding="utf-8")

    def apply(self, change: Change) -> Version:
        unit = self._unit(change.unit_id)
        if unit.max_bytes is not None and len(change.content.encode()) > unit.max_bytes:
            raise SurfaceError(f"{unit.id} exceeds max_bytes={unit.max_bytes}")
        path = self._unit_path(unit.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(change.content, encoding="utf-8")
        self._git("add", "--", self._rel(path))
        status = self._git("status", "--porcelain")
        if status.strip():
            self._git("-c", "commit.gpgsign=false", "commit", "-m", f"kochab apply {unit.id}")
        return self.head()

    def rollback(self, to: Version) -> None:
        self._git("reset", "--hard", to)

    def diff(self, a: Version, b: Version) -> str:
        return self._git("diff", "--no-color", a, b) or ""

    def baseline(self) -> Version:
        return self._git("rev-parse", self.BASELINE_REF).strip()

    def accepted(self) -> Version:
        return self._git("rev-parse", self.ACCEPTED_REF).strip()

    def mark_accepted(self, version: Version) -> Version:
        resolved = self._git("rev-parse", version).strip()
        self._git("update-ref", self.ACCEPTED_REF, resolved)
        return resolved

    def restore_accepted(self) -> Version:
        version = self.accepted()
        self.rollback(version)
        return version

    @contextmanager
    def materialize(self, version: Version) -> Iterator[Path]:
        """Export a version to an isolated temporary tree."""
        root = self.work_dir.parent / "eval"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="surface-", dir=root) as raw:
            dest = Path(raw)
            blob = subprocess.run(
                ["git", "archive", "--format=tar", version],
                cwd=self.work_dir,
                capture_output=True,
                check=False,
            )
            if blob.returncode != 0:
                raise SurfaceError(
                    (blob.stderr or b"").decode("utf-8", "replace") or "git archive failed"
                )
            with tarfile.open(fileobj=io.BytesIO(blob.stdout), mode="r") as tar:
                if sys.version_info >= (3, 12):
                    tar.extractall(dest, filter="data")
                else:
                    tar.extractall(dest)
            yield dest

    def _unit(self, unit_id: str) -> UnitManifest:
        if unit_id not in self._units:
            raise SurfaceError(f"unknown unit: {unit_id}")
        return self._units[unit_id]

    def _unit_path(self, unit_id: str) -> Path:
        unit = self._unit(unit_id)
        path = (self.work_dir / unit.path).resolve()
        try:
            path.relative_to(self.work_dir.resolve())
        except ValueError as exc:
            raise SurfaceError("path escapes work copy") from exc
        return path

    def _copy_from_source(self, unit: UnitManifest) -> None:
        src = (self.source_root / unit.path).resolve()
        try:
            src.relative_to(self.source_root.resolve())
        except ValueError as exc:
            raise SurfaceError("source path escapes host root") from exc
        dest = self._unit_path(unit.id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    def _rel(self, path: Path) -> str:
        return os.path.relpath(path, self.work_dir)

    def _root_commit(self) -> Version:
        return self._git("rev-list", "--max-parents=0", "HEAD").strip()

    def _ensure_ref(self, ref: str, version: Version) -> None:
        proc = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", ref],
            cwd=self.work_dir,
            check=False,
        )
        if proc.returncode != 0:
            self._git("update-ref", ref, version)

    def _git(self, *args: str) -> str:
        env = os.environ.copy()
        env.setdefault("GIT_PAGER", "cat")
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        proc = subprocess.run(
            ["git", *args],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
        )
        if proc.returncode != 0:
            raise SurfaceError(proc.stderr.strip() or proc.stdout.strip() or "git failed")
        return proc.stdout or ""
