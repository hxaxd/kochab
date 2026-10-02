"""Offline behavioral checks, including CLI runs; scripted replies do not establish model quality."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from kochab.records import CaseResult, Evaluation, Judgment, Trace
from kochab.rubric import JudgmentBatch, RubricCase
from examples.paper_summary.rubric_calibration import (
    PaperScoreConsistency, PaperRubricEvaluator, PaperRubricOptimizer, calibrate_rubric,
)
from examples.paper_summary.artifacts import ArtifactStore
from examples.paper_summary.agent_evolution import PaperPromptOptimizer, evolve_agent
from examples.paper_summary.benchmark import PaperBenchmarkRunner, build_benchmark
from examples.paper_summary.verifiers import DIMENSIONS


class ImprovementTests(unittest.TestCase):
    """验证 Rubric 重复评分以及 Agent 候选采纳的边界。"""

    def setUp(self):
        # 每次从固定论文和独立仓库开始，避免跨测试残留。
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paper = Path(self.temp.name) / "paper.txt"
        self.paper.write_text("A improves recall on B.", encoding="utf-8")
        self.store = ArtifactStore()
        self.model = self.store.put({"model": "offline-test-double"})
        self.benchmark = build_benchmark(self.store, [self.paper], "Read evidence", self.model,
                                         lambda _: self.scoring(2), min_chars=5, max_chars=100)
        self.agent = self.store.put({"prompt": "baseline", "model": self.model.ref, "max_steps": 3})
        self.candidate = self.store.put({**self.store.get(self.agent), "prompt": "candidate"})
        self.output = {"summary": "A improves recall on B.", "citations": [{"page": 1, "quote": "recall"}]}

    def scoring(self, value):
        # 返回 Judge 需要的四个分数和理由，供离线调用替身使用。
        return json.dumps({"scores": dict.fromkeys(DIMENSIONS, value), "reason": "Offline test evidence."})

    def evaluation(self, agent=None, score=2, valid=True):
        # 快速构造一条格式通过或失败的完整评测结果。
        task = self.benchmark.tasks[0]
        trace = Trace(task, agent or self.agent, self.store.put([]),
                      self.store.put(self.output if valid else {}), task.initial_state)
        judgments = (Judgment(self.benchmark.verifiers[0].definition, {"passed": valid}, "Offline check."),
                     Judgment(self.benchmark.verifiers[1].definition,
                              dict.fromkeys(DIMENSIONS, score) if valid else {"status": "not_scored"}, "Offline judge."))
        return Evaluation(self.benchmark.definition, trace.agent, (CaseResult(trace, judgments),))

    def test_repeat_is_parallel_and_uses_identical_fixed_evidence(self):
        """同步栅栏确保重复判断真的并行，并且消费同一份轨迹。"""
        barrier = threading.Barrier(3)
        prompts = []
        def complete(prompt):
            prompts.append(prompt)
            barrier.wait(timeout=5)
            return self.scoring(3)
        trace = self.evaluation().cases[0].trace
        # 若实现串行调用，三个工作线程无法同时到达此栅栏。
        batch = PaperRubricEvaluator(self.store, self.model, complete).repeat(
            self.store.put("Frozen rubric"), trace, repeats=3)
        self.assertEqual(len(batch.judgments), 3)
        self.assertEqual(len(set(prompts)), 1)
        self.assertEqual(batch.trace, trace)
        self.assertTrue(all(j.value == dict.fromkeys(DIMENSIONS, 3) for j in batch.judgments))

    def test_spread_flags_disagreement_without_confusing_skips_with_agreement(self):
        """评分差异达到阈值才标记；错误判断也不能误认为一致。"""
        trace = self.evaluation().cases[0].trace
        rubric = self.store.put("rubric")
        judgments = tuple(Judgment(rubric, dict.fromkeys(DIMENSIONS, n), "Evidence.") for n in (1, 3, 2))
        self.assertIsNotNone(PaperScoreConsistency().check(JudgmentBatch(rubric, trace, judgments)))
        self.assertIsNone(PaperScoreConsistency().check(JudgmentBatch(rubric, trace, judgments[1:])))
        error = Judgment(rubric, {"status": "error"}, "API error")
        self.assertIsNotNone(PaperScoreConsistency().check(JudgmentBatch(rubric, trace, (error, error))))

    def test_draft_disagreement_revision_and_recheck_leave_human_review_pending(self):
        """跑完初稿、找出分歧、修订并在相同轨迹上再次评分。"""
        calls, seen, counter = [], [], iter((1, 3, 1))
        def optimize(prompt):
            calls.append(prompt)
            return json.dumps({"rubric": "initial" if len(calls) == 1 else "revised", "summary": "Clarify evidence boundaries."})
        lock = threading.Lock()
        def judge(prompt):
            seen.append(prompt)
            with lock:
                score = next(counter) if prompt.startswith("initial") else 3
            return self.scoring(score)
        # 第一次三项故意不一致；修订后的三项使用一致分数。
        source = self.evaluation()
        report = calibrate_rubric(source, PaperRubricOptimizer(self.store, self.model, optimize),
                           PaperRubricEvaluator(self.store, self.model, judge), rounds=2, repeats=3)
        self.assertEqual(len(calls), 2)
        self.assertIn("Score spread", calls[1])
        self.assertIn("A improves recall on B.", calls[1])
        self.assertEqual(len(report["rounds"]), 2)
        # 即使现在一致，也只生成待审候选，不自动声称已由人认可。
        self.assertEqual(report["status"], "pending_human_review")
        self.assertIsNone(report["human_review"])
        self.assertEqual(report["rounds"][-1]["disagreements"], [])
        self.assertEqual(report["review_samples"][0]["trace"], asdict(source.cases[0].trace))
        self.assertEqual(len(seen), 6)
        self.assertEqual(self.benchmark.verifiers[1].rubric,
                         self.store.put(Path("examples/paper_summary/rubric.md").read_text(encoding="utf-8")))

    def test_errors_and_invalid_outputs_do_not_trigger_rubric_revision(self):
        """Judge 异常和无语义证据都不应触发 Rubric 修改。"""
        def must_not_optimize(_):
            self.fail("Do not revise on infrastructure failure or absent semantic evidence.")
        rubric = self.store.put("initial")
        for valid, status in ((True, "evaluation_error"), (False, "insufficient_evidence")):
            report = calibrate_rubric(self.evaluation(valid=valid),
                               PaperRubricOptimizer(self.store, self.model, must_not_optimize),
                               PaperRubricEvaluator(self.store, self.model, lambda _: "malformed"),
                               rounds=1, repeats=2, rubric=rubric)
            self.assertEqual(report["status"], status)
            self.assertIsNone(report["human_review"])

    def test_selection_rejects_regressions_ties_and_judge_errors(self):
        """逐题检查退化和异常；只有实际改善且无退化才采纳。"""
        optimizer = PaperPromptOptimizer(self.store, self.model, lambda _: "")
        baseline = self.evaluation(score=2)
        self.assertTrue(optimizer.decide(baseline, self.evaluation(self.candidate, score=3)).keep)
        self.assertFalse(optimizer.decide(baseline, self.evaluation(self.candidate, score=2)).keep)
        self.assertFalse(optimizer.decide(baseline, self.evaluation(self.candidate, valid=False)).keep)
        # 构造某维度下降和 Judge 报错两个单独拒绝条件。
        case = self.evaluation(self.candidate, score=4).cases[0]
        for value in ({**case.judgments[1].value, "faithfulness": 1}, {"status": "error"}):
            changed = replace(case, judgments=(case.judgments[0], replace(case.judgments[1], value=value)))
            trial = replace(baseline, agent=self.candidate, cases=(changed,))
            self.assertFalse(optimizer.decide(baseline, trial).keep)
        invalid = self.evaluation(valid=False)
        self.assertFalse(optimizer.decide(invalid, self.evaluation(self.candidate, score=2)).keep)
        self.assertTrue(optimizer.decide(invalid, self.evaluation(self.candidate, score=3)).keep)

    def test_selection_requires_complete_fixed_benchmark_and_configuration(self):
        """拒绝测试集、不完整评测和同时改动模型配置的对照。"""
        optimizer = PaperPromptOptimizer(self.store, self.model, lambda _: "")
        baseline = self.evaluation()
        other = self.store.put({**self.store.get(self.benchmark.definition), "split": "test"})
        changed = self.store.put({**self.store.get(self.candidate), "max_steps": 99})
        for trial in (replace(baseline, benchmark=other), replace(baseline, cases=()), self.evaluation(changed)):
            with self.assertRaises(ValueError):
                optimizer.decide(baseline, trial)
        case = baseline.cases[0]
        altered = replace(case, judgments=(case.judgments[0], replace(case.judgments[1], verifier=other)))
        self.assertFalse(optimizer.decide(baseline, replace(baseline, cases=(altered,))).keep)

    def test_evolution_records_acceptance_then_rejection_and_retains_winner(self):
        """第二轮退化不会覆盖第一轮已采纳的好版本。"""
        # 优化器先提一个有效版本，再提一个会被格式验证挡下的版本。
        replies = iter(("candidate", "regression"))
        optimizer = PaperPromptOptimizer(self.store, self.model, lambda _: json.dumps({
            "prompt": next(replies), "reason": "Offline evidence-based change."}))
        # Only the solver changes; the same judge and benchmark serve both trials.
        # 替身对首个候选给出较好的答案，对第二个候选给出过短答案。
        def complete(prompt):
            text = "A improves recall on B." if prompt.startswith("candidate") else "x"
            return json.dumps({**self.output, "summary": text})
        evaluator = PaperBenchmarkRunner(self.store, complete)
        baseline = self.evaluation(score=1)
        final, records = evolve_agent(evaluator, self.benchmark, baseline, optimizer, rounds=3)
        self.assertEqual(final.agent, self.candidate)
        self.assertEqual([r["decision"]["keep"] for r in records], [True, False])
        self.assertTrue(all(r["trial"] in self.store.contents for r in records))

    def test_rejected_rubric_report_samples_belong_to_retained_version(self):
        """候选新增分歧后被拒绝，抽检材料必须仍指向之前的标准。"""
        source = self.evaluation()
        first = source.cases[0]
        second = replace(first, trace=replace(first.trace, task=replace(first.trace.task, id="second")))
        manifest = {**self.store.get(source.benchmark),
                    "tasks": [asdict(c.trace.task) for c in (first, second)]}
        source = replace(source, benchmark=self.store.put(manifest), cases=(first, second))
        initial = self.store.put("initial")
        revised = self.store.put("revised")
        def repeat(rubric, trace, *, repeats):
            values = (1, 3) if trace.task.id != "second" or rubric == revised else (2, 2)
            return JudgmentBatch(rubric, trace, tuple(
                Judgment(rubric, dict.fromkeys(DIMENSIONS, n), "Offline judgment") for n in values))
        # 初始只有一条分歧，修订后两条均有分歧，所以选择器拒绝候选。
        from types import SimpleNamespace
        report = calibrate_rubric(source, PaperRubricOptimizer(self.store, self.model, lambda _: json.dumps(
            {"rubric": "revised", "summary": "Offline candidate"})), SimpleNamespace(repeat=repeat),
            rounds=2, repeats=2, rubric=initial)
        self.assertEqual(report["stop_reason"], "rejected")
        self.assertEqual(report["candidate_rubric"], initial.ref)
        self.assertEqual(report["rounds"][-1]["rubric"], revised.ref)
        self.assertFalse(report["rounds"][-1]["decision"]["keep"])
        self.assertTrue(all(sample["rubric"] == asdict(initial) for sample in report["review_samples"]))

    def test_rubric_optimizer_passes_open_materials_without_inventing_labels(self):
        """实际修订适配器展开原文、轨迹、专家反馈和多版标准，不要求分数。"""
        trace = self.evaluation().cases[0].trace
        other = replace(trace, result=self.store.put({**self.output, "summary": "Other interpretation"}))
        current, alternative = self.store.put("current standard"), self.store.put("alternative standard")
        feedback = self.store.put("专家意见：需要说明适用边界。")
        cases = (RubricCase(traces=(trace, other), instruction="两条轨迹存在争议"),
                 RubricCase(traces=(trace, other), feedback=(feedback,)),
                 RubricCase(traces=(trace, other), feedback=(self.store.put({"preferred": 1}),)),
                 RubricCase(rubrics=(current, alternative), instruction="比较标准"))
        prompts = []
        def complete(prompt):
            prompts.append(prompt)
            return json.dumps({"rubric": "revised standard", "summary": "Offline revision"})
        optimizer = PaperRubricOptimizer(self.store, self.model, complete)
        revision = optimizer.revise(current, cases)
        context = json.loads(prompts[0].split("\n")[-1])
        self.assertEqual(context["cases"][0]["feedback"], [])
        self.assertEqual(context["cases"][0]["judgments"], [])
        self.assertEqual(len(context["cases"][0]["traces"]), 2)
        self.assertIn("A improves recall on B.", str(context["cases"][0]["traces"][0]["paper"]))
        self.assertEqual(context["cases"][1]["feedback"][0]["content"], self.store.get(feedback))
        self.assertEqual(context["cases"][2]["feedback"][0]["content"], {"preferred": 1})
        self.assertEqual([r["content"] for r in context["cases"][3]["rubrics"]],
                         ["current standard", "alternative standard"])
        self.assertEqual(self.store.get(revision.rubric), "revised standard")

    def test_cli_runs_calibration_and_evolution_as_separate_experiments(self):
        """用替身模型分别跑两个 CLI 实验，并验证参数互斥与人工复用入口。"""
        # 测试内创建的临时后端只返回可预测 JSON，不调用在线模型。
        directory = Path(self.temp.name)
        (directory / "offline_improvement_backend.py").write_text('''import json
dimensions = ["faithfulness", "coverage", "evidence", "clarity"]
def complete(prompt):
 if prompt.startswith("# Rubric"):
  return json.dumps({"rubric": "CALIBRATED", "summary": "Offline draft."})
 if prompt.startswith("# 根据评测"):
  return json.dumps({"prompt": "CANDIDATE", "reason": "Offline improvement."})
 if "评判材料：" in prompt:
  score = 3 if 'Candidate summary' in prompt else 2
  return json.dumps({"scores": dict.fromkeys(dimensions, score), "reason": "Offline judgment."})
 summary = "Candidate summary" if prompt.startswith("CANDIDATE") else "Baseline summary"
 return json.dumps({"summary": summary, "citations": [{"page": 1, "quote": "recall"}]})
''', encoding="utf-8")
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(root / "src"), str(directory))))
        command = [sys.executable, "-m", "examples.paper_summary.run", str(self.paper),
                   "--goal", "Read evidence", "--model", "offline_improvement_backend:complete",
                   "--model-id", "offline-test-double", "--min-chars", "5", "--max-chars", "100"]
        # 每次子进程只运行一个实验，结果写入独立新文件。
        for flag in ("--evolve", "--calibrate-rubric"):
            output = directory / (flag + ".json")
            subprocess.run([*command, flag, "1", "--out", str(output)], cwd=root, env=env,
                           check=True, capture_output=True, text=True)
            report = json.loads(output.read_text(encoding="utf-8"))
            if flag == "--evolve":
                self.assertTrue(report["evolution_rounds"][0]["decision"]["keep"])
                self.assertIsNone(report["rubric_calibration"])
            else:
                self.assertEqual(report["rubric_calibration"]["status"], "pending_human_review")
                self.assertEqual(report["evolution_rounds"], [])
        # 同时指定两个改进环节时应由命令行参数解析器拒绝。
        rejected = subprocess.run([*command, "--evolve", "1", "--calibrate-rubric", "1",
                                   "--out", str(directory / "mixed.json")], cwd=root, env=env,
                                  capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertFalse((directory / "mixed.json").exists())
        # A reviewed text can be supplied explicitly for a fresh evaluation.
        # 模拟人工审阅后显式装入提示词和 Rubric，检查新配置进入评测。
        custom_prompt, custom_rubric = directory / "prompt.md", directory / "rubric.md"
        custom_prompt.write_text("CANDIDATE", encoding="utf-8")
        custom_rubric.write_text("REVIEWED STANDARD", encoding="utf-8")
        output = directory / "custom.json"
        subprocess.run([*command, "--agent-prompt", str(custom_prompt), "--rubric", str(custom_rubric),
                        "--out", str(output)], cwd=root, env=env, check=True, capture_output=True, text=True)
        report = json.loads(output.read_text(encoding="utf-8"))
        agent = report["artifacts"][report["evaluation"]["agent"]["ref"]]
        self.assertEqual(agent["prompt"], "CANDIDATE")
        verifier_ref = report["evaluation"]["cases"][0]["judgments"][1]["verifier"]["ref"]
        verifier = report["artifacts"][verifier_ref]
        self.assertEqual(report["artifacts"][verifier["rubric"]], "REVIEWED STANDARD")


if __name__ == "__main__":
    unittest.main()
