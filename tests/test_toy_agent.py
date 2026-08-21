from __future__ import annotations

import importlib.util

from helpers import GENERAL_SYSTEM, STUFFED_SYSTEM, TOY

spec = importlib.util.spec_from_file_location("toy_agent", TOY / "eval" / "agent.py")
agent = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(agent)


def test_general_policies_answer_holdout_wording() -> None:
    text = agent.answer(GENERAL_SYSTEM, "What is the standard loan period for circulating material?")
    assert "21 days" in text


def test_stuffed_train_faq_misses_holdout_wording() -> None:
    text = agent.answer(STUFFED_SYSTEM, "What is the standard loan period for circulating material?")
    assert "21 days" not in text
