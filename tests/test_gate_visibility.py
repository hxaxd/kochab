from __future__ import annotations

from pathlib import Path

from kochab.round import opening_brief
from kochab.session import open_session
from helpers import copy_toy


def test_suites_hide_holdout_ids(tmp_path: Path) -> None:
    session = open_session(copy_toy(tmp_path))
    ids = {row.id for row in session.gated_eval.suites()}
    assert "tr_loan" in ids
    assert "ho_loan" not in ids


def test_eval_run_rejects_holdout_id(tmp_path: Path) -> None:
    session = open_session(copy_toy(tmp_path))
    result = session.tools.dispatch(
        {
            "id": "1",
            "function": {
                "name": "eval_run",
                "arguments": '{"case_ids": ["ho_loan"]}',
            },
        }
    )
    assert "unknown case" in result["content"]
    assert "ho_loan" not in result["content"]


def test_eval_gold_rejects_holdout_id(tmp_path: Path) -> None:
    session = open_session(copy_toy(tmp_path))
    result = session.tools.dispatch(
        {
            "id": "1",
            "function": {"name": "eval_gold", "arguments": '{"case_id": "ho_loan"}'},
        }
    )
    assert "unknown case" in result["content"]
    assert "ho_loan" not in result["content"]


def test_opening_brief_hides_holdout(tmp_path: Path) -> None:
    session = open_session(copy_toy(tmp_path))
    text = opening_brief(session)
    assert "Train cases: 10" in text
    assert "ho_loan" not in text
    assert "holdout" not in text.lower()
