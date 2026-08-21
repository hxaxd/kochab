from __future__ import annotations

import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator
from typing import Any


class KochabState:
    """Journal + notes living next to the work copy. Not part of the host surface."""

    def __init__(self, state_dir: Path) -> None:
        self.dir = state_dir
        self.journal_path = state_dir / "journal.jsonl"
        self.notes_path = state_dir / "notes.md"

    def notes(self) -> str:
        if not self.notes_path.exists():
            return ""
        return self.notes_path.read_text(encoding="utf-8")

    def write_notes(self, content: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._atomic_text(self.notes_path, content)

    def journal(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.journal_path.exists():
            return []
        lines = [
            json.loads(line)
            for line in self.journal_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return lines[-limit:]

    def append(self, event: str, **payload: Any) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **payload,
        }
        with self.journal_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def write_json(self, name: str, payload: Any) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / name
        self._atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
        return path

    def read_json(self, name: str) -> Any | None:
        path = self.dir / name
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_round(
        self,
        messages: list[dict[str, Any]],
        outcome: dict[str, Any] | None,
        *,
        status: str,
        reason: str,
        error: str | None = None,
    ) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        path = self.dir / "rounds" / f"{stamp}-{uuid.uuid4().hex[:8]}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_text(
            path,
            json.dumps(
                {
                    "status": status,
                    "reason": reason,
                    "error": error,
                    "outcome": outcome,
                    "messages": messages,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        return path

    @contextmanager
    def file_transaction(self, names: list[str]) -> Iterator[None]:
        """Restore selected state files exactly if a multi-file update fails."""
        paths = [self.dir / name for name in names]
        snapshots = {path: path.read_bytes() if path.exists() else None for path in paths}
        try:
            yield
        except BaseException:
            for path, content in snapshots.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    self._atomic_bytes(path, content)
            raise

    def _atomic_text(self, path: Path, content: str) -> None:
        self._atomic_bytes(path, content.encode("utf-8"))

    def _atomic_bytes(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(raw, path)
        except BaseException:
            try:
                os.unlink(raw)
            except FileNotFoundError:
                pass
            raise
