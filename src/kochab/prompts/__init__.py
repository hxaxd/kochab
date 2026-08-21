from __future__ import annotations

from pathlib import Path


def evolve_prompt() -> str:
    return (Path(__file__).with_name("evolve.md")).read_text(encoding="utf-8")
