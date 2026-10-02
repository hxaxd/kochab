"""Synthesis admission and adversarial feedback, using explicit offline doubles."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from kochab.records import Evaluation
from examples.paper_summary.agent import INSTRUCTION
from examples.paper_summary.artifacts import ArtifactStore
from examples.paper_summary.benchmark import PaperBenchmarkRunner, build_benchmark
from examples.paper_summary.task_synthesis import PaperTaskSynthesizer, PaperTaskValidator, expand_benchmark


class TaskSynthesisTests(unittest.TestCase):
    """检查候选生成、审核、入集和多轮反馈，不衡量替身模型质量。"""

    def setUp(self):
        # 固定论文包含实验结论和适用边界，供新任务围绕范围构造。
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ArtifactStore()
        paper = Path(self.temp.name) / "paper.txt"
        paper.write_text("A improves recall on dataset B.\fOther datasets were not studied.", encoding="utf-8")
        self.model = self.store.put({"model": "offline-double"})
        self.scores = json.dumps({"scores": dict.fromkeys(["faithfulness", "coverage", "evidence", "clarity"], 2),
                                 "reason": "Offline evidence for testing only."})
        self.benchmark = build_benchmark(self.store, [paper], "Summarize the paper", self.model,
                                          lambda _: self.scores, min_chars=5, max_chars=100)
        self.parent = self.benchmark.tasks[0]
        # 私有参考解故意带唯一标记，可检查求解提示词是否错误泄漏答案。
        self.reference = {"summary": "PRIVATE_REFERENCE: findings apply only to B.",
                          "citations": [{"page": 2, "quote": "Other datasets were not studied."}]}
        self.candidate = {"parent": self.parent.id, "goal": "Summarize the limits of generalization.",
                          "reason": "The solver may overgeneralize the reported result.", "reference": self.reference}
        self.feedback = Evaluation(self.benchmark.definition, self.model, ())

    def synthesizer(self, items):
        # 返回指定候选，便于分别测试有效、重复和无效生成结果。
        return PaperTaskSynthesizer(self.store, self.model, lambda _: json.dumps(items))

    def validator(self, accepted=True):
        # 返回可控制通过与拒绝结果的审核替身。
        return PaperTaskValidator(self.store, self.model,
                                  lambda _: json.dumps({"valid": accepted, "reason": "Offline review."}))

    def test_admission_creates_new_version_preserving_tasks_and_conditions(self):
        """接纳候选生成新版本，同时保留全部原题和环境条件。"""
        expanded, records = expand_benchmark(self.benchmark, self.feedback,
                                             self.synthesizer([self.candidate]), self.validator(), count=1)
        self.assertNotEqual(expanded.definition, self.benchmark.definition)
        self.assertEqual(len(self.benchmark.tasks), 1)
        self.assertEqual(expanded.tasks[0], self.parent)
        self.assertEqual(expanded.tasks[1].initial_state, self.parent.initial_state)
        self.assertEqual(expanded.tasks[1].seed, self.parent.seed)
        self.assertEqual(expanded.verifiers, self.benchmark.verifiers)
        self.assertTrue(records[0]["review"]["accepted"])

    def test_invalid_reference_is_rejected_before_model_review(self):
        """确定性引文核对失败后，不再调用语义审核模型。"""
        candidate = {**self.candidate, "reference": {**self.reference,
                     "citations": [{"page": 2, "quote": "This is not in the paper."}]}}
        def forbidden(_):
            self.fail("Invalid evidence must not reach semantic review")
        expanded, records = expand_benchmark(self.benchmark, self.feedback, self.synthesizer([candidate]),
                                             PaperTaskValidator(self.store, self.model, forbidden), count=1)
        self.assertEqual(expanded.definition, self.benchmark.definition)
        self.assertFalse(records[0]["review"]["accepted"])

    def test_duplicate_candidates_are_not_admitted_twice(self):
        """批内第一项入集后，第二个相同问题必须被识别为重复。"""
        expanded, records = expand_benchmark(self.benchmark, self.feedback,
                                             self.synthesizer([self.candidate, self.candidate]),
                                             self.validator(), count=2)
        self.assertEqual(len(expanded.tasks), 2)
        self.assertEqual([r["review"]["accepted"] for r in records], [True, False])

    def test_review_rejection_and_error_do_not_grow_benchmark(self):
        """明确拒绝或无法解析审核结果都不能改变 Benchmark 版本。"""
        for response in ['{"valid": false, "reason": "Unanswerable."}', '{"valid": "yes"}']:
            validator = PaperTaskValidator(self.store, self.model, lambda _, value=response: value)
            expanded, records = expand_benchmark(self.benchmark, self.feedback,
                                                 self.synthesizer([self.candidate]), validator, count=1)
            self.assertEqual(expanded.definition, self.benchmark.definition)
            self.assertFalse(records[0]["review"]["accepted"])

    def test_existing_constraints_cannot_be_weakened(self):
        """新题只能改变允许修改的阅读目的，不能放宽长度约束。"""
        proposal = self.synthesizer([self.candidate]).propose(self.benchmark, None, count=1)[0]
        problem = {**self.store.get(proposal.task.problem), "min_chars": 1}
        changed = replace(proposal, task=replace(proposal.task, problem=self.store.put(problem)))
        self.assertFalse(self.validator().validate(changed, self.benchmark).accepted)

    def test_holdout_and_mismatched_feedback_are_rejected(self):
        """封存测试和错误 Benchmark 版本的反馈都不能进入出题上下文。"""
        holdout = replace(self.benchmark, definition=self.store.put({"split": "test"}))
        for benchmark, feedback in [(holdout, None), (self.benchmark, replace(self.feedback, benchmark=holdout.definition))]:
            with self.assertRaises(ValueError):
                self.synthesizer([self.candidate]).propose(benchmark, feedback, count=1)

    def test_solver_feedback_reaches_next_generation_without_leaking_reference(self):
        """真实轨迹会反馈给下一轮出题者，私有参考答案不会交给求解者。"""
        expanded, _ = expand_benchmark(self.benchmark, self.feedback, self.synthesizer([self.candidate]),
                                        self.validator(), count=1)
        prompts = []
        output = {"summary": "A improves recall on B.",
                  "citations": [{"page": 1, "quote": "A improves recall on dataset B."}]}
        def solve(prompt):
            prompts.append(prompt)
            return json.dumps(output)
        agent = self.store.put({"prompt": INSTRUCTION, "max_steps": 2})
        feedback = PaperBenchmarkRunner(self.store, solve).run(agent, expanded)
        self.assertTrue(all("PRIVATE_REFERENCE" not in prompt for prompt in prompts))
        generation_prompts = []
        def generate(prompt):
            generation_prompts.append(prompt)
            return "[]"
        proposals = PaperTaskSynthesizer(self.store, self.model, generate).propose(expanded, feedback, count=1)
        self.assertEqual(proposals, ())
        self.assertIn("A improves recall on B.", generation_prompts[0])
        self.assertIn("Offline evidence for testing only.", generation_prompts[0])
        self.assertIn(expanded.tasks[1].id, generation_prompts[0])

    def test_cli_runs_two_feedback_driven_synthesis_rounds(self):
        """用真实命令行顺序跑完两轮出题、审核、入集和复测。"""
        # 临时模块根据角色返回离线 JSON，明确不依赖线上服务。
        directory = Path(self.temp.name)
        (directory / "offline_synthesis_backend.py").write_text('''import json
generation = 0
def complete(prompt):
 global generation
 if prompt.startswith("# 合成"):
  generation += 1
  context = json.loads(prompt.split("\\n")[-1])
  assert context["feedback"]
  return json.dumps([{"parent": context["tasks"][-1]["id"], "goal": f"Challenge {generation}",
   "reason": "Offline test candidate", "reference": {"summary": "PRIVATE_REFERENCE on dataset B.",
   "citations": [{"page": 1, "quote": "A improves recall on dataset B."}]}}])
 if prompt.startswith("独立审核"):
  return json.dumps({"valid": True, "reason": "Offline review only."})
 if prompt.startswith("你根据论文"):
  return json.dumps({"scores": dict.fromkeys(["faithfulness", "coverage", "evidence", "clarity"], 2),
   "reason": "Offline scoring only."})
 assert "PRIVATE_REFERENCE" not in prompt
 return json.dumps({"summary": "A improves recall on dataset B.",
   "citations": [{"page": 1, "quote": "A improves recall on dataset B."}]})
''', encoding="utf-8")
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(root / "src"), str(directory)]))
        subprocess.run([sys.executable, "-m", "examples.paper_summary.run", str(directory / "paper.txt"),
                        "--goal", "Read the paper", "--model", "offline_synthesis_backend:complete",
                        "--model-id", "offline-double", "--min-chars", "5", "--max-chars", "100",
                        "--synthesize", "1", "--synthesis-rounds", "2", "--out", str(directory / "report.json")],
                       cwd=root, env=env, check=True, capture_output=True, text=True)
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["evaluation"]["cases"]), 3)
        self.assertEqual(len(report["synthesis_rounds"]), 2)
        for i, round_record in enumerate(report["synthesis_rounds"], 1):
            source = report["artifacts"][round_record["source_evaluation"]]
            self.assertEqual(len(source["cases"]), i)
            self.assertTrue(round_record["candidates"][0]["review"]["accepted"])
            self.assertIn(round_record["evaluation"], report["artifacts"])


if __name__ == "__main__":
    unittest.main()
