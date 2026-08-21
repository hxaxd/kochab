from __future__ import annotations

import json

from kochab.adapters.eval_formats import parse_eval_output


def test_native_result_has_host_defined_pass_state() -> None:
    result = parse_eval_output(
        json.dumps(
            {
                "score": 0.8,
                "passed": True,
                "metrics": {"accuracy": 0.8},
                "cases": [
                    {"id": "a", "score": 0.8, "passed": True, "feedback": "host accepts"}
                ],
            }
        )
    )
    assert result.passed is True
    assert result.metrics["accuracy"] == 0.8


def test_promptfoo_v3_result_is_normalized() -> None:
    result = parse_eval_output(
        json.dumps(
            {
                "results": {
                    "version": 3,
                    "stats": {"successes": 1, "failures": 1},
                    "results": [
                        {
                            "testIdx": 0,
                            "success": True,
                            "score": 1,
                            "response": {"output": "ok"},
                            "gradingResult": {"reason": "good"},
                        },
                        {
                            "testIdx": 1,
                            "success": False,
                            "score": 0,
                            "error": "bad",
                        },
                    ],
                }
            }
        ),
        "promptfoo",
    )
    assert result.score == 0.5
    assert result.passed is False
    assert result.cases[0].output == "ok"


def test_generic_jsonl_result_is_normalized() -> None:
    result = parse_eval_output(
        '{"sample_id":"one","score":1,"success":true,"response":"ok"}\n'
        '{"sample_id":"two","score":0,"success":false,"reason":"bad"}\n',
        "jsonl",
    )
    assert result.score == 0.5
    assert result.cases[1].feedback == "bad"


def test_junit_result_is_normalized() -> None:
    result = parse_eval_output(
        """<testsuite tests="2" failures="1">
        <testcase classname="agent" name="good"><system-out>answer</system-out></testcase>
        <testcase classname="agent" name="bad"><failure message="wrong" /></testcase>
        </testsuite>""",
        "junit",
    )
    assert result.score == 0.5
    assert result.passed is False
    assert result.cases[1].feedback == "wrong"


def test_inspect_json_log_is_normalized() -> None:
    result = parse_eval_output(
        json.dumps(
            {
                "status": "success",
                "samples": [
                    {
                        "id": "sample-1",
                        "output": {"completion": "Paris"},
                        "scores": {
                            "match": {"value": "C", "explanation": "correct"}
                        },
                    }
                ],
            }
        ),
        "inspect",
    )
    assert result.passed is True
    assert result.cases[0].feedback == "correct"
