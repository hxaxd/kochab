"""One teaching policy: revise the prompt, keep only observed improvements without regressions."""
import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from kochab.agent_evolution import AgentProposal, SelectionDecision, evolve_agent as run_evolution
from kochab.benchmark import Benchmark, BenchmarkRunner
from kochab.records import Artifact, Evaluation

from .artifacts import ArtifactStore
from .benchmark import require_development_evaluation
from .verifiers import DIMENSIONS, valid_scores


class PaperPromptOptimizer:
    """只修改答题提示词，让对照实验的变化来源保持清楚。"""

    def __init__(self, artifacts: ArtifactStore, model: Artifact, complete: Callable[[str], str]):
        # 提示词生成器单独注入，求解 Agent 和 Judge 无需与它使用同一模型。
        self.artifacts, self.model, self.complete = artifacts, model, complete

    def propose(self, baseline: Evaluation) -> AgentProposal:
        # 只用完整开发集证据生成提案，不从封存测试中学习。
        require_development_evaluation(self.artifacts, baseline)
        # 基线配置是新候选的底稿，模型、步数等非提示词项保持不变。
        config = self.artifacts.get(baseline.agent)
        # 为修改模型汇总任务、原文、运行轨迹和评分理由。
        context = {"agent": config, "cases": [
            {"task": self.artifacts.get(case.trace.task.problem),
             "paper": self.artifacts.get(case.trace.task.initial_state),
             "events": self.artifacts.get(case.trace.events),
             "output": self.artifacts.get(case.trace.result),
             "judgments": [asdict(j) for j in case.judgments]} for case in baseline.cases]}
        # 示例自己的模板约束修改范围，再附上本轮真实证据。
        prompt = (Path(__file__).parent / "prompts/agent-revise.md").read_text(encoding="utf-8")
        prompt += "\n" + json.dumps(context, ensure_ascii=False)
        # 保存原始修订输入和输出，拒绝时也能检查提案质量。
        raw = self.complete(prompt)
        record = self.artifacts.put({"model": self.model.ref, "prompt": prompt, "response": raw})
        # 候选必须同时给出完整提示词和可以审核的修改理由。
        result = json.loads(raw)
        if (not isinstance(result, dict)
                or any(not isinstance(result.get(k), str) or not result[k].strip() for k in ("prompt", "reason"))):
            raise ValueError("Optimizer must return a prompt and a reason.")
        # 替换且只替换提示词，候选本身由内容哈希确定版本。
        candidate = self.artifacts.put({**config, "prompt": result["prompt"]})
        return AgentProposal(candidate, result["reason"], (self.artifacts.put(asdict(baseline)), record))

    def decide(self, baseline: Evaluation, trial: Evaluation) -> SelectionDecision:
        # 对照双方都必须是在开发集、所有任务上的完整评测。
        require_development_evaluation(self.artifacts, baseline)
        require_development_evaluation(self.artifacts, trial)
        # Benchmark 不同就无法把结果变化归因于提示词修改。
        if baseline.benchmark != trial.benchmark:
            raise ValueError("Compare candidates under the same benchmark and verifiers.")
        # 比较完整配置，确认除了 prompt 外没有同时更改其他条件。
        configs = [self.artifacts.get(e.agent) for e in (baseline, trial)]
        if {k: v for k, v in configs[0].items() if k != "prompt"} != {
                k: v for k, v in configs[1].items() if k != "prompt"}:
            raise ValueError("Only the agent prompt may change in this example.")
        # 每个案例应有清单里声明的全部验证器，且顺序和版本相同。
        expected = self.artifacts.get(baseline.benchmark)["verifiers"]
        improved = False
        # 逐题比较，不让某一题的大幅提升掩盖另一题的退化。
        for before, after in zip(baseline.cases, trial.cases):
            for case in (before, after):
                if len(case.judgments) != 2 or [j.verifier.ref for j in case.judgments] != expected:
                    return SelectionDecision(False, "Incomplete or changed verifiers; comparison is inconclusive.")
                mechanical, semantic = [j.value for j in case.judgments]
                if not isinstance(mechanical, dict) or type(mechanical.get("passed")) is not bool:
                    return SelectionDecision(False, "Mechanical verification error; comparison is inconclusive.")
                if mechanical["passed"]:
                    if not valid_scores(semantic):
                        return SelectionDecision(False, "Semantic verification error; comparison is inconclusive.")
                elif semantic != {"status": "not_scored"}:
                    return SelectionDecision(False, "Unexpected judgment for invalid output.")
            # 先检查机械有效性，只有通过时语义分数才有意义。
            valid_before, valid_after = [c.judgments[0].value["passed"] for c in (before, after)]
            if valid_before and not valid_after:
                return SelectionDecision(False, f"Deterministic regression on {before.trace.task.id}.")
            if valid_before and valid_after:
                # 已有效任务的各项都不能降分；至少一项升分才构成改善。
                old, new = before.judgments[1].value, after.judgments[1].value
                if any(new[d] < old[d] for d in DIMENSIONS):
                    return SelectionDecision(False, f"Rubric regression on {before.trace.task.id}.")
                improved = improved or any(new[d] > old[d] for d in DIMENSIONS)
            elif valid_after:
                # 原先无效的任务，只有新结果有效且各维度至少为 3 才算改善。
                improved = improved or all(v >= 3 for v in after.judgments[1].value.values())
        # 任一退化或异常已提前拒绝；到这里才根据改善标记作最终选择。
        return SelectionDecision(improved, "Observed improvement without per-case regression." if improved
                        else "No qualifying improvement on this development run.")


def evolve_agent(runner: BenchmarkRunner, benchmark: Benchmark, baseline: Evaluation,
                 optimizer: PaperPromptOptimizer, *, rounds: int) -> tuple[Evaluation, list[dict]]:
    """领域策略留在示例，通用循环只负责提案、复测和采纳。"""
    result = run_evolution(runner, benchmark, baseline, optimizer, rounds=rounds)
    artifacts, records = optimizer.artifacts, []
    # 沿用命令行报告格式，保存完整评测的引用以便检查。
    for step in result.rounds:
        entry = {"baseline": artifacts.put(asdict(step.baseline)).ref,
                 "selection_policy": "per-case-no-regression-v1"}
        if step.proposal is not None:
            entry["proposal"] = asdict(step.proposal)
        if step.trial is not None:
            entry["trial"] = artifacts.put(asdict(step.trial)).ref
        if step.decision is not None:
            entry["decision"] = asdict(step.decision)
        if step.error is not None:
            entry["error"] = step.error
        records.append(entry)
    return result.evaluation, records
