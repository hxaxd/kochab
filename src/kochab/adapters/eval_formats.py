from __future__ import annotations

from typing import Literal

from kochab.adapters.eval_parsers import inspect, junit, native, promptfoo
from kochab.adapters.eval_parsers.common import EvalFormatError
from kochab.contracts.models import EvalResult

EvalFormat = Literal["kochab", "jsonl", "promptfoo", "junit", "inspect"]


def parse_eval_output(
    payload: str,
    format: EvalFormat = "kochab",
    pass_threshold: float = 1.0,
) -> EvalResult:
    parsers = {
        "kochab": native.parse_json,
        "jsonl": native.parse_jsonl,
        "promptfoo": promptfoo.parse,
        "junit": junit.parse,
        "inspect": inspect.parse,
    }
    try:
        parser = parsers[format]
    except KeyError as exc:
        raise EvalFormatError(f"unsupported eval format: {format}") from exc
    return parser(payload, pass_threshold)


__all__ = ["EvalFormat", "EvalFormatError", "parse_eval_output"]
