"""Check human-directed data feedback, without treating test replies as model-quality evidence."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from kochab.data_feedback import UsageRecord
from examples.paper_summary.agent import INSTRUCTION
from examples.paper_summary.artifacts import ArtifactStore
from examples.paper_summary.benchmark import PaperBenchmarkRunner, build_benchmark
from examples.paper_summary.data_feedback import PaperDataCurator, load_regressions
from examples.paper_summary.verifiers import DIMENSIONS


class DataFeedbackTests(unittest.TestCase):
    """验证人类选样、环境重放和回归题再导入 Benchmark 的路径。"""

    def setUp(self):
        # 每项测试共用一篇临时论文，结束后自动清除文件。
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paper = self.root / "paper.txt"
        self.paper.write_text("A improves recall on B.", encoding="utf-8")
        self.store = ArtifactStore()
        self.model = self.store.put({"model": "offline-test-double"})
        self.judge = lambda _: json.dumps({"scores": dict.fromkeys(DIMENSIONS, 3), "reason": "Offline test."})
        self.benchmark = build_benchmark(self.store, [self.paper], "Read evidence", self.model,
                                         self.judge, min_chars=5, max_chars=100)
        # 替身依次读论文并提交摘要，只用于检验代码流程。
        replies = iter([{"tool": "read_page", "arguments": {"page": 1}},
                        {"summary": "A improves recall.", "citations": [{"page": 1, "quote": "recall"}]}])
        agent = self.store.put({"prompt": INSTRUCTION, "max_steps": 3})
        runner = PaperBenchmarkRunner(self.store, lambda _: json.dumps(next(replies)))
        self.evaluation = runner.run(agent, self.benchmark)
        self.trace = self.evaluation.cases[0].trace
        self.curator = PaperDataCurator(self.store)

    def usage(self, **changes):
        # 默认人工意见选中一个训练回合，并将任务标记为回归项。
        review = {"reviewer": "offline-test-reviewer", "notes": "Explicit test annotation.",
                  "regression": True, "training_steps": [1]}
        return UsageRecord(self.trace, self.store.put({**review, **changes}))

    def test_regression_replays_frozen_evidence_and_rejects_changed_tool_results(self):
        """源文件删除后仍可重放；篡改工具返回值后拒绝回归。"""
        # 先确认环境重放使用固定快照和原任务要求。
        self.paper.unlink()
        task = self.curator.regression(self.usage())
        self.assertEqual(task.initial_state, self.trace.task.initial_state)
        self.assertEqual(task.problem, self.trace.task.problem)
        # 再篡改一次已保存的结果，验证重放能发现不一致。
        events = self.store.get(self.trace.events)
        tool_event = next(event for event in events if "tool" in event)
        tool_event["result"]["text"] = "Changed evidence"
        usage = replace(self.usage(), trace=replace(self.trace, events=self.store.put(events)))
        self.assertIsNone(self.curator.regression(usage))
        self.assertIsNone(self.curator.regression(self.usage(regression=False)))

    def test_selected_steps_keep_tool_context_and_deduplicate(self):
        """只导出人工选中的轮次，并保留此前读到的上下文。"""
        # 两次选择同一调用，按内容哈希只保留一个样本。
        prepared = self.curator.prepare(self.usage(training_steps=[1, 1]))
        self.assertEqual(len(prepared.samples), 1)
        messages = self.store.get(prepared.samples[0])["messages"]
        # 提示中包含工具结果，模型看到的完整输入被保留。
        self.assertIn("tool_result", messages[0]["content"])
        self.assertIn("A improves recall on B.", messages[0]["content"])
        self.assertEqual(json.loads(messages[1]["content"])["summary"], "A improves recall.")
        self.assertEqual(self.curator.prepare(self.usage(training_steps=[])).samples, ())
        # 审核人缺失、错误序号类型和越界序号都不能导出。
        for review in ({"reviewer": ""}, {"training_steps": [True]}, {"training_steps": [99]}):
            with self.assertRaises(ValueError):
                self.curator.prepare(self.usage(**review))
        # 被选中的调用没有模型响应时不能伪装成有效监督样本。
        events = self.store.get(self.trace.events)
        del next(event for event in events if "model_output" in event)["model_output"]
        broken = replace(self.usage(training_steps=[0]), trace=replace(self.trace, events=self.store.put(events)))
        with self.assertRaises(ValueError):
            self.curator.prepare(broken)

    def test_cli_exports_feedback_then_runner_evaluates_imported_regression(self):
        """从报告和审核意见生成反馈包，再通过下一次评测导入回归任务。"""
        # 写出一个真实 CLI 会读取的运行报告和按任务 ID 索引的审核文件。
        report, reviews, bundle = [self.root / name for name in ("report.json", "reviews.json", "feedback.json")]
        report.write_text(json.dumps({"evaluation": asdict(self.evaluation), "artifacts": self.store.contents}))
        reviews.write_text(json.dumps({self.trace.task.id: self.store.get(self.usage().feedback)}))
        # 用子进程走命令行入口，确认离线模型和工作目录可正常解析。
        repo = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(repo / "src"), str(self.root))))
        subprocess.run([sys.executable, "-m", "examples.paper_summary.data_feedback", str(report), str(reviews),
                        "--out", str(bundle)], cwd=repo, env=env, check=True, capture_output=True, text=True)
        # 同一任务不重复加入；更换阅读目标后则会新增一项任务。
        exported = json.loads(bundle.read_text())
        self.assertEqual(len(exported["training_samples"]), 1)
        self.assertEqual(len(exported["regression_tasks"]), 1)
        # Same tasks are not duplicated; a different reading goal is a genuinely new task.
        self.assertEqual(load_regressions(self.store, self.benchmark, bundle).definition, self.benchmark.definition)
        new = build_benchmark(self.store, [self.paper], "Read a different aspect", self.model,
                              self.judge, min_chars=5, max_chars=100)
        expanded = load_regressions(self.store, new, bundle)
        self.assertEqual(len(expanded.tasks), 2)
        self.assertEqual(load_regressions(self.store, expanded, bundle).definition, expanded.definition)
        self.assertEqual(expanded.verifiers, new.verifiers)
        changed = self.store.put({**self.store.get(new.definition), "environment": "different-version"})
        with self.assertRaises(ValueError):
            load_regressions(self.store, replace(new, definition=changed), bundle)
        # 后续基线评测会实际执行导入的回归任务。
        (self.root / "offline_feedback_backend.py").write_text('''import json
def complete(prompt):
 if "评判材料：" in prompt:
  return json.dumps({"scores": dict.fromkeys(["faithfulness", "coverage", "evidence", "clarity"], 3), "reason": "Offline test."})
 return json.dumps({"summary": "A improves recall.", "citations": [{"page": 1, "quote": "recall"}]})
''')
        result = self.root / "new-report.json"
        subprocess.run([sys.executable, "-m", "examples.paper_summary.run", str(self.paper),
                        "--goal", "Different goal", "--model", "offline_feedback_backend:complete",
                        "--model-id", "offline-test", "--min-chars", "5", "--max-chars", "100",
                        "--regressions", str(bundle), "--out", str(result)],
                       cwd=repo, env=env, check=True, capture_output=True, text=True)
        cases = json.loads(result.read_text())["evaluation"]["cases"]
        self.assertEqual(len(cases), 2)
        self.assertTrue(all(case["judgments"][0]["value"]["passed"] for case in cases))
        # 测试集报告必须在导出任何数据之前被拒绝。
        heldout = self.store.put({**self.store.get(self.benchmark.definition), "split": "test"})
        report.write_text(json.dumps({"evaluation": asdict(replace(self.evaluation, benchmark=heldout)),
                                      "artifacts": self.store.contents}))
        rejected = self.root / "heldout-feedback.json"
        response = subprocess.run([sys.executable, "-m", "examples.paper_summary.data_feedback",
                                   str(report), str(reviews), "--out", str(rejected)],
                                  cwd=repo, env=env, capture_output=True, text=True)
        self.assertNotEqual(response.returncode, 0)
        self.assertFalse(rejected.exists())

    def test_cli_preserves_feedback_for_trace_without_final_snapshot(self):
        """终态缺失不会阻止读取原有执行证据和人类反馈。"""
        case = replace(self.evaluation.cases[0], trace=replace(self.trace, final_state=None))
        evaluation = replace(self.evaluation, cases=(case,))
        report, reviews, output = [self.root / name for name in ("missing-state.json", "review.json", "out.json")]
        report.write_text(json.dumps({"evaluation": asdict(evaluation), "artifacts": self.store.contents}))
        reviews.write_text(json.dumps({self.trace.task.id: self.store.get(self.usage(training_steps=[]).feedback)}))
        repo = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(repo / "src"))
        subprocess.run([sys.executable, "-m", "examples.paper_summary.data_feedback", str(report), str(reviews),
                        "--out", str(output)], cwd=repo, env=env, check=True, capture_output=True, text=True)
        record = json.loads(output.read_text())["records"][0]
        self.assertIsNone(record["prepared"]["source"]["trace"]["final_state"])
        self.assertEqual(record["prepared"]["samples"], [])

    def test_loading_rejects_artifact_corruption(self):
        """导入时重新计算哈希；内容与引用不符就停止。"""
        ref = self.store.put({"snapshot": "original"})
        corrupted = {**self.store.contents, ref.ref: {"snapshot": "changed"}}
        with self.assertRaises(ValueError):
            ArtifactStore(corrupted)


if __name__ == "__main__":
    unittest.main()
