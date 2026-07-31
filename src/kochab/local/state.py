from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKIP_DIRS = {
    "__pycache__", "node_modules", "venv", "dist", "build",
}


def excluded(rel: Path) -> bool:
    return any(part.lower() in SKIP_DIRS or part.startswith(".") for part in rel.parts)


def skill_files(root: Path) -> list[Path]:
    """Inventory versioned files, including binary assets, without links."""
    files = []
    for directory, dirs, names in os.walk(root):
        base = Path(directory)
        dirs[:] = [name for name in dirs if not excluded((base / name).relative_to(root))]
        for name in dirs + names:
            path = base / name
            if excluded(path.relative_to(root)):
                continue
            if path.resolve() != path:
                raise ValueError(f"skill files must be local regular files, not links: {path}")
            if path.is_file():
                files.append(path)
    return sorted(files)


def text_content(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class State:
    """Versioning for one skill folder; the folder itself is the candidate."""

    def __init__(self, host: Path) -> None:
        self.host = host.resolve()
        self.dir = self.host / ".kochab"
        self.repo = self.dir / "repo"

    def check(self) -> None:
        if not (self.repo / "HEAD").is_file() or self.repo.resolve() != self.repo:
            raise ValueError(f"no kochab repository at {self.repo}; run kochab init")

    def journal(self, kind: str, **payload: Any) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **payload}
        with (self.dir / "journal.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def candidate(self) -> str:
        skill_files(self.host)  # Validate the file boundary the repository stages.
        git(self, "add", "--all")
        return git(self, "write-tree").decode().strip()

    def accept(self) -> str:
        skill = self.host / "SKILL.md"
        if not skill.is_file() or text_content(skill) is None:
            raise ValueError("the skill folder must retain a UTF-8 SKILL.md")
        candidate = self.candidate()
        if candidate != rev(self, "refs/kochab/accepted^{tree}"):
            git(self, "commit", "-q", "-m", "accept")
            git(self, "update-ref", "refs/kochab/accepted", "HEAD")
            self.journal("accept", candidate=candidate, commit=rev(self, "HEAD"))
        return rev(self, "refs/kochab/accepted")

    def rollback(self) -> None:
        # Tracked files return to the accepted version and this round's new
        # files are removed; ignored directories such as .kochab stay untouched.
        self.check()
        git(self, "reset", "--hard", "refs/kochab/accepted")
        git(self, "clean", "-fdq")
        self.journal("rollback", accepted=rev(self, "refs/kochab/accepted"))


def git(state: State, *args: str) -> bytes:
    proc = subprocess.run(
        ["git",
         "--git-dir=" + str(state.repo), "--work-tree=" + str(state.host), *args],
        capture_output=True,
    )
    if proc.returncode:
        raise ValueError((proc.stderr or proc.stdout).decode("utf-8", errors="replace").strip())
    return proc.stdout


def init_state(host: Path) -> State:
    state = State(host)
    if state.repo.exists():
        state.check()
        return state
    files = skill_files(state.host)
    if state.host / "SKILL.md" not in files or text_content(state.host / "SKILL.md") is None:
        raise ValueError("host must be a skill folder containing a UTF-8 SKILL.md")
    if state.repo.resolve() != state.repo:
        raise ValueError(f"the kochab repository must be a local directory: {state.repo}")
    state.repo.mkdir(parents=True)
    git(state, "init", "-q")
    info = state.repo / "info"
    (info / "exclude").write_text(
        ".kochab/\n.*\n" + "".join(f"{name}/\n" for name in sorted(SKIP_DIRS)),
        encoding="utf-8",
    )
    for key, value in {
        "user.name": "kochab", "user.email": "kochab@localhost",
        "core.bare": "false", "commit.gpgSign": "false", "core.autocrlf": "false",
        "core.excludesFile": str(info / "exclude"),
    }.items():
        git(state, "config", key, value)
    # Skill files are versioned byte-for-byte, including binary assets.
    (info / "attributes").write_text("* -text -filter -ident\n", encoding="utf-8")
    candidate = state.candidate()
    git(state, "commit", "-q", "-m", "baseline")
    git(state, "update-ref", "refs/kochab/baseline", "HEAD")
    git(state, "update-ref", "refs/kochab/accepted", "HEAD")
    state.journal("init", candidate=candidate, commit=rev(state, "HEAD"))
    return state


def diff(state: State) -> str:
    state.candidate()
    return git(state, "diff", "--cached", "--binary", "refs/kochab/accepted").decode("utf-8", errors="replace")


def rev(state: State, ref: str) -> str:
    return git(state, "rev-parse", "--verify", ref).decode().strip()
