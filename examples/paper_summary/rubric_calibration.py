"""Calibrate a rubric on frozen traces; always leave the final candidate for human review."""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from kochab.agent_evolution import SelectionDecision
from kochab.records import Artifact, Evaluation, Judgment, Trace
from kochab.rubric import (Disagreement, JudgmentBatch, RubricAssessment, RubricCase,
                           RubricRevision, disagreement_case, evolve_rubric)

from .artifacts import ArtifactStore
from .benchmark import require_development_evaluation
from .verifiers import DIMENSIONS, OUTPUT_CONTRACT, RubricVerifier, valid_scores


class PaperRubricEvaluator:
    """对同一份固定证据重复调用 Judge，不重新运行答题 Agent。"""

    def __init__(self, artifacts: ArtifactStore, judge: Artifact, complete: Callable[[str], str]):
        # Judge 版本和模型调用由调用者注入，便于替换或单独部署。
        self.artifacts, self.judge, self.complete = artifacts, judge, complete

    def repeat(self, rubric: Artifact, trace: Trace, *, repeats: int) -> JudgmentBatch:
        # 一次判断无法估计不一致，因此至少要求两个独立结果。
        if repeats < 2:
            raise ValueError("Use at least two independent judgments.")
        verifier = RubricVerifier(self.artifacts, rubric, self.judge, self.complete)
        # 将单次模型异常转成带证据的 Judgment，保留在这一批结果中。
        def once(_):
            try:
                return verifier.verify(trace)
            except Exception as exc:
                return Judgment(verifier.definition, {"status": "error"},
                                f"{type(exc).__name__}: {exc}", (trace.result, rubric))
        # The injected completion function must support concurrent independent calls.
        # 最多并发四个请求，避免一次批量校准无界占用资源。
        with ThreadPoolExecutor(max_workers=min(4, repeats)) as pool:
            judgments = tuple(pool.map(once, range(repeats)))
        return JudgmentBatch(rubric, trace, judgments)


class PaperScoreConsistency:
    """本例用数值分数极差识别分歧；阈值属于领域策略，不是核心规定。"""

    def check(self, batch: JudgmentBatch) -> Disagreement | None:
        # 只比较同一 Rubric 对同一轨迹产生的本批判断。
        values = [j.value for j in batch.judgments]
        if len(values) < 2:
            raise ValueError("JudgmentConsistency requires repeated judgments.")
        # 格式检查一致地阻止语义评分时，没有分歧案例需要校准。
        if all(v == {"status": "not_scored"} for v in values):
            return None
        if not all(valid_scores(value) for value in values):
            return Disagreement(batch, "Judgments are incomplete or failed; investigate before revision.")
        # 任一维度极差达到 2 分就标记，并说明是哪些维度。
        different = [d for d in DIMENSIONS if max(v[d] for v in values) - min(v[d] for v in values) >= 2]
        return Disagreement(batch, "Score spread >= 2: " + ", ".join(different)) if different else None


class PaperRubricOptimizer:
    """生成评分初稿或依据分歧提出新版标准，并保存模型往返记录。"""

    def __init__(self, artifacts: ArtifactStore, model: Artifact, complete: Callable[[str], str]):
        self.artifacts, self.model, self.complete = artifacts, model, complete
        self.records: list[Artifact] = []

    def _generate(self, template: str, context: object) -> RubricRevision:
        # 冷启动和修订共用 JSON 输出格式与本例固定的评分字段。
        prompt = (Path(__file__).parent / "prompts" / template).read_text(encoding="utf-8")
        prompt += "\n本例固定四个评分维度及其 0–4 方向，不改变任务约束或输出协议：\n" + OUTPUT_CONTRACT
        prompt += '\n本次只输出 JSON：{"rubric":"完整评分标准","summary":"依据、修改理由及未解决事项"}。\n'
        prompt += json.dumps(context, ensure_ascii=False)
        # 单独记录一次评分标准生成调用，之后可以检查修改理由。
        raw = self.complete(prompt)
        self.records.append(self.artifacts.put({"model": self.model.ref, "prompt": prompt, "response": raw}))
        # 拒绝缺少 Rubric 正文或摘要的输出，避免空标准进入下一轮。
        result = json.loads(raw)
        if (not isinstance(result, dict)
                or any(not isinstance(result.get(k), str) or not result[k].strip() for k in ("rubric", "summary"))):
            raise ValueError("Rubric optimizer must return a rubric and an analysis summary.")
        return RubricRevision(self.artifacts.put(result["rubric"]), result["summary"])

    def draft(self, requirement: Artifact) -> Artifact:
        # 初稿直接根据任务需求、证据要求和验证边界生成。
        return self._generate("rubric-draft.md", self.artifacts.get(requirement)).rubric

    def revise(self, rubric: Artifact, cases: tuple[RubricCase, ...]) -> RubricRevision:
        # 不限定轨迹数量或反馈格式，其他 Rubric 版本也可以作为比较材料。
        if not cases:
            raise ValueError("Supply evidence or an investigation instruction.")
        context = {"rubric": self.artifacts.get(rubric), "cases": [
            {"instruction": case.instruction,
             "traces": [{"trace": asdict(trace),
                         "task": self.artifacts.get(trace.task.problem),
                         "paper": self.artifacts.get(trace.task.initial_state),
                         "output": self.artifacts.get(trace.result),
                         "events": self.artifacts.get(trace.events)} for trace in case.traces],
             "judgments": [asdict(j) for j in case.judgments],
             "rubrics": [{"ref": r.ref, "content": self.artifacts.get(r)} for r in case.rubrics],
             "feedback": [{"ref": f.ref, "content": self.artifacts.get(f)} for f in case.feedback]}
            for case in cases]}
        return self._generate("rubric-revise.md", context)


class PaperRubricAssessor:
    """重复评判是本例采用的一种复评策略，不是核心循环的输入限制。"""

    def __init__(self, artifacts: ArtifactStore, judge: PaperRubricEvaluator, repeats: int):
        self.artifacts, self.judge, self.repeats = artifacts, judge, repeats

    def assess(self, rubric: Artifact, cases: tuple[RubricCase, ...]) -> RubricAssessment:
        # 核心每轮传入同一批原始案例；一条轨迹出现多次时只评一次。
        traces = []
        for case in cases:
            for trace in case.traces:
                if trace not in traces:
                    traces.append(trace)
        batches = tuple(self.judge.repeat(rubric, trace, repeats=self.repeats) for trace in traces)
        checked = (PaperScoreConsistency().check(batch) for batch in batches)
        disagreements = tuple(item for item in checked if item is not None)
        record = self.artifacts.put({"rubric": rubric.ref, "batches": [asdict(b) for b in batches],
                                     "disagreements": [asdict(d) for d in disagreements]})
        # 模型错误和缺少可评分证据，不能伪装成已校准。
        if any(j.value == {"status": "error"} for b in batches for j in b.judgments):
            status = "error"
        elif not batches or all(j.value == {"status": "not_scored"} for b in batches for j in b.judgments):
            status = "insufficient_evidence"
        else:
            status = "ready" if disagreements else "complete"
        return RubricAssessment(rubric, tuple(disagreement_case(d) for d in disagreements), (record,),
                                "Repeated-judgment consistency; correctness still requires review.", status)


class PaperRubricSelector:
    """仅接受分歧案例数不增加的候选；这不是人类对标准正确性的认可。"""

    def decide(self, baseline: RubricAssessment, trial: RubricAssessment) -> SelectionDecision:
        keep = len(trial.findings) <= len(baseline.findings)
        return SelectionDecision(keep, "Disputed case count did not increase." if keep
                                 else "More disputed cases; retain the previous rubric.")


def calibrate_rubric(evaluation: Evaluation, optimizer: PaperRubricOptimizer, judge: PaperRubricEvaluator,
              *, rounds: int, repeats: int, rubric: Artifact | None = None) -> dict:
    """Draft unless a rubric is supplied; rejudge identical evidence after every revision."""
    # rounds 限制修订次数；初始检查之外，每个实际候选再复评一次。
    if rounds < 1 or repeats < 2:
        raise ValueError("Use a positive revision budget and at least two judgments.")
    artifacts = optimizer.artifacts
    require_development_evaluation(artifacts, evaluation)
    # 从真实任务和机械检查边界构造冷启动要求，不编造额外业务标准。
    manifest = artifacts.get(evaluation.benchmark)
    requirement = artifacts.put({"benchmark": manifest, "tasks": [
        artifacts.get(case.trace.task.problem) for case in evaluation.cases],
        "deterministic_checks": "structure, non-whitespace length, page number and literal quotation",
        "semantic_dimensions": list(DIMENSIONS)})
    report = {"source_evaluation": artifacts.put(asdict(evaluation)).ref, "rounds": [],
              "consistency_policy": "any-dimension-spread-at-least-2-v1",
              "status": "pending_human_review", "human_review": None}
    try:
        # 可从内置初稿开始，也可显式传入人类已审核的现有版本。
        current = rubric or optimizer.draft(requirement)
        report["initial_rubric"] = current.ref
        cases = tuple(RubricCase(traces=(case.trace,), instruction="检查评分依据和边界是否清楚。")
                      for case in evaluation.cases)
        outcome = evolve_rubric(current, cases, optimizer, PaperRubricAssessor(artifacts, judge, repeats),
                                PaperRubricSelector(), rounds=rounds)
        # 报告包含初始检查和每次候选复评；拒绝的候选也不会丢失。
        if outcome.initial is not None:
            report["rounds"].append(artifacts.get(outcome.initial.evidence[0]))
        for step in outcome.rounds:
            if step.revision is not None:
                report["rounds"][-1]["revision"] = asdict(step.revision)
            if step.trial is not None:
                report["rounds"].append(artifacts.get(step.trial.evidence[0]))
            if step.decision is not None:
                report["rounds"][-1]["decision"] = asdict(step.decision)
            if step.error is not None:
                report["error"] = step.error
        report["candidate_rubric"] = outcome.rubric.ref
        report["stop_reason"] = outcome.stop_reason
        if outcome.assessment is not None:
            # 抽检针对最后采纳版本的全部案例，不能误用被拒绝版本的评分。
            report["review_samples"] = artifacts.get(outcome.assessment.evidence[0])["batches"]
        if outcome.stop_reason == "error":
            report["status"] = "error" if outcome.error or "error" in report else "evaluation_error"
        elif outcome.stop_reason == "insufficient_evidence":
            report["status"] = "insufficient_evidence"
        if outcome.error:
            report["error"] = outcome.error
    except Exception as exc:
        # 把异常状态留在报告；候选仍待人类核对，不自动激活。
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["optimizer_calls"] = [record.ref for record in optimizer.records]
    return report
