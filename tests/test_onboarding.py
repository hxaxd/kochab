from __future__ import annotations

from pathlib import Path

import pytest

from helpers import copy_toy
from kochab.contracts.models import TraceFilter
from kochab.onboarding import FrozenBindingError, onboard_host
from kochab.session import open_session


def test_onboarding_exercises_and_freezes_all_ports(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    report = onboard_host(host, freeze=True)
    assert report.ready is True
    assert report.frozen is True
    assert report.train_cases == 10
    assert report.holdout_cases == 6
    assert report.trace_probe == "readable"

    session = open_session(host, require_frozen=True)
    refs = session.host.traces.query(TraceFilter(limit=100))
    assert len(refs) == 10
    visible = "\n".join(session.host.traces.read(ref).model_dump_json() for ref in refs)
    assert "ho_loan" not in visible
    assert "standard loan period" not in visible


def test_frozen_binding_detects_drift(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    onboard_host(host, freeze=True)
    criteria = host / "eval" / "CRITERIA.md"
    criteria.write_text(criteria.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    with pytest.raises(FrozenBindingError, match="criteria_sha256"):
        open_session(host, require_frozen=True)


@pytest.mark.parametrize("relative", ["eval/run.py", "eval/cases.json"])
def test_frozen_binding_detects_eval_dependency_drift(
    tmp_path: Path, relative: str
) -> None:
    host = copy_toy(tmp_path)
    onboard_host(host, freeze=True)
    dependency = host / relative
    content = dependency.read_text(encoding="utf-8")
    if relative.endswith(".json"):
        content = content.replace("How long can I keep", "For how long can I keep", 1)
    else:
        content += "\n"
    dependency.write_text(content, encoding="utf-8")
    expected = "eval_dependencies" if relative.endswith(".py") else "case_catalog"
    with pytest.raises(FrozenBindingError, match=expected):
        open_session(host, require_frozen=True)


def test_surface_rebind_requires_explicit_state_reset(tmp_path: Path) -> None:
    host = copy_toy(tmp_path)
    onboard_host(host, freeze=True)
    source = host / "surface" / "SYSTEM.md"
    source.write_text("new source\n", encoding="utf-8")

    with pytest.raises(FrozenBindingError, match="--reset-state"):
        onboard_host(host, freeze=True)

    report = onboard_host(host, freeze=True, reset_state=True)
    assert report.state_backup is not None
    assert Path(report.state_backup).is_dir()
    session = open_session(host, require_frozen=True)
    assert session.host.surface.read("system") == "new source\n"
