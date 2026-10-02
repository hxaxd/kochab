"""Offline contract checks. Scripted model replies are test doubles, not paper results."""
import json
import tempfile
import unittest
from pathlib import Path

from kochab.records import Trace
from examples.paper_summary.agent import INSTRUCTION
from examples.paper_summary.artifacts import ArtifactStore
from examples.paper_summary.environment import PaperEnvironment
from examples.paper_summary.benchmark import PaperBenchmarkRunner, build_benchmark
from examples.paper_summary.verifiers import FormatVerifier, RubricVerifier


class PaperSummaryTests(unittest.TestCase):
    """检查论文环境的快照、工具、验证器和单轮评测入口。"""

    def setUp(self):
        # 临时目录和独立内容仓库让每个测试相互隔离。
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ArtifactStore()
        self.paper = Path(self.temp.name) / "paper.txt"
        self.paper.write_text("A improves recall.\fThe study covers only dataset B.", encoding="utf-8")
        self.model = self.store.put({"model": "offline-test-double"})
        # 通用成功输出可用于多个验证器测试，不依赖真实模型答案。
        self.output = {"summary": "A improves recall.", "citations": [{"page": 1, "quote": "improves recall"}]}
        self.scores = {"scores": dict.fromkeys(["faithfulness", "coverage", "evidence", "clarity"], 3),
                       "reason": "Offline test judgment."}

    def benchmark(self, complete=lambda _: "", papers=None):
        # 大部分检查使用短的正文范围，缩小样例输入。
        return build_benchmark(self.store, papers or [self.paper], "Read the evidence", self.model,
                               complete, min_chars=5, max_chars=40)

    def trace(self, output):
        # 将指定结果包成轨迹，便于单独验证规则。
        task = self.benchmark().tasks[0]
        return Trace(task, self.model, self.store.put([]), self.store.put(output), task.initial_state)

    def test_artifacts_freeze_mutable_input_and_return_copies(self):
        """改原对象或读出副本都不能改变已经存储的内容。"""
        data = {"items": [1]}
        ref = self.store.put(data)
        data["items"].append(2)
        self.store.get(ref)["items"].append(3)
        self.assertEqual(self.store.get(ref), {"items": [1]})

    def test_reset_replays_fixed_paper_without_leaking_session_state(self):
        """修改源文件后，重复 reset 仍读取相同快照并得到相同终态。"""
        benchmark = self.benchmark()
        task = benchmark.tasks[0]
        self.paper.write_text("Changed after the snapshot.", encoding="utf-8")
        snapshots = []
        # 两轮均从全新事件列表开始，再执行相同观察和工具动作。
        for _ in range(2):
            session = benchmark.environment.reset(task.initial_state, seed=task.seed)
            self.assertEqual(session.events, [])
            self.assertEqual(session.observe()["page_count"], 2)
            result = session.call("read_page", {"page": 1})
            self.assertEqual(result["text"], "A improves recall.")
            result["text"] = "tampered"
            self.assertEqual(session.call("search", {"query": "dataset"})[0]["page"], 2)
            snapshots.append(session.snapshot())
            self.assertEqual(session.events[1]["result"]["text"], "A improves recall.")
            session.close()
            with self.assertRaises(RuntimeError):
                session.observe()
        self.assertEqual(snapshots[0], snapshots[1])

    def test_tools_reject_invalid_calls(self):
        """错误页码、额外参数和未注册工具都应由环境拒绝。"""
        benchmark = self.benchmark()
        session = benchmark.environment.reset(benchmark.tasks[0].initial_state, seed=0)
        for tool, arguments in [("read_page", {"page": 0}), ("read_page", {"page": True}),
                                ("read_page", {"page": 3}), ("search", {"query": " "}),
                                ("unknown", {})]:
            with self.subTest(tool=tool, arguments=arguments), self.assertRaises(ValueError):
                session.call(tool, arguments)
        session.close()

    def test_format_checks_reject_length_structure_and_false_citations(self):
        """机械验证覆盖结构、长度、页码和原文逐字引文。"""
        verifier = FormatVerifier(self.store)
        self.assertTrue(verifier.verify(self.trace(self.output)).value["passed"])
        invalid = [None, {}, {**self.output, "summary": " "},
                   {**self.output, "summary": "x" * 41}, {**self.output, "citations": []},
                   {**self.output, "citations": [{"page": True, "quote": "A"}]},
                   {**self.output, "citations": [{"page": 1, "quote": "invented evidence"}]},
                   {**self.output, "citations": [{"page": 1, "quote": " "}]}]
        for output in invalid:
            with self.subTest(output=output):
                self.assertFalse(verifier.verify(self.trace(output)).value["passed"])

    def test_rubric_skips_invalid_output_and_rejects_malformed_scores(self):
        """格式检查失败时跳过 Judge；Judge 输出类型错误时不生成评分。"""
        rubric = self.store.put("Judge the summary.")
        def should_not_call(_):
            self.fail("Judge called despite deterministic failure")
        verifier = RubricVerifier(self.store, rubric, self.model, should_not_call)
        self.assertEqual(verifier.verify(self.trace({})).value, {"status": "not_scored"})
        malformed = {**self.scores, "scores": {**self.scores["scores"], "faithfulness": True}}
        verifier = RubricVerifier(self.store, rubric, self.model, lambda _: json.dumps(malformed))
        with self.assertRaises(ValueError):
            verifier.verify(self.trace(self.output))

    def test_runner_creates_and_closes_environment_for_each_paper(self):
        """每篇论文各自 reset 和 close，轨迹还保存模型请求及响应。"""
        second = Path(self.temp.name) / "second.txt"
        second.write_text("A improves recall.\fSecond paper details.", encoding="utf-8")
        replies = iter([json.dumps(reply) for reply in [
            {"tool": "read_page", "arguments": {"page": 1}}, self.output, self.scores,
            {"tool": "read_page", "arguments": {"page": 1}}, self.output, self.scores,
        ]])
        complete = lambda _: next(replies)
        benchmark = self.benchmark(complete, [self.paper, second])
        sessions = []
        reset = benchmark.environment.reset
        def tracked_reset(initial_state, *, seed):
            session = reset(initial_state, seed=seed)
            sessions.append(session)
            return session
        # 包装 reset 来保留每个真实会话引用，随后检查全部关闭。
        benchmark.environment.reset = tracked_reset
        agent = self.store.put({"prompt": INSTRUCTION, "max_steps": 3})
        result = PaperBenchmarkRunner(self.store, complete).run(agent, benchmark)
        self.assertEqual(len(result.cases), 2)
        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(session.closed for session in sessions))
        for case in result.cases:
            self.assertTrue(case.judgments[0].value["passed"])
            self.assertEqual(case.judgments[1].value, self.scores["scores"])
            events = self.store.get(case.trace.events)
            self.assertEqual(events[-1], {"termination": "completed"})
            self.assertIn("model_input", events[1])
            self.assertIn("model_output", events[1])

    def test_agent_budget_failure_is_retained_as_evidence(self):
        """耗尽工具调用预算会记录错误，并由两个验证器分别处理。"""
        complete = lambda _: '{"tool": "read_page", "arguments": {"page": 1}}'
        benchmark = self.benchmark(complete)
        agent = self.store.put({"prompt": INSTRUCTION, "max_steps": 1})
        case = PaperBenchmarkRunner(self.store, complete).run(agent, benchmark).cases[0]
        self.assertIn("error", self.store.get(case.trace.result))
        self.assertEqual(self.store.get(case.trace.events)[-1]["termination"], "error")
        self.assertFalse(case.judgments[0].value["passed"])
        self.assertEqual(case.judgments[1].value, {"status": "not_scored"})


if __name__ == "__main__":
    unittest.main()
