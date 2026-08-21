from __future__ import annotations

from pathlib import Path

from kochab.contracts.models import Change
from kochab.session import open_session
from helpers import copy_toy


def test_work_copy_does_not_touch_host_surface(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    original = (host / "surface" / "SYSTEM.md").read_text(encoding="utf-8")
    session = open_session(host)
    session.host.surface.apply(Change(unit_id="system", content="changed\n"))
    assert (host / "surface" / "SYSTEM.md").read_text(encoding="utf-8") == original
    assert session.host.surface.read("system") == "changed\n"


def test_rollback_restores_round_start(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    session = open_session(host)
    start = session.host.surface.head()
    session.host.surface.apply(Change(unit_id="system", content="v2\n"))
    session.host.surface.rollback(start)
    assert "9am" in session.host.surface.read("system")
