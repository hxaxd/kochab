"""Turn explicit human feedback into replayable tasks and selected training turns."""
import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from kochab.benchmark import Benchmark
from kochab.data_feedback import PreparedData, UsageRecord
from kochab.records import Artifact, Task, Trace

from .artifacts import ArtifactStore
from .environment import PaperEnvironment


def read_task(value: dict) -> Task:
    # 报告中的引用原本是普通字典；转换回 Artifact 后才能直接在代码中使用。
    return Task(value["id"], Artifact(**value["problem"]), Artifact(**value["initial_state"]), value["seed"])


class PaperDataCurator:
    """遵循人类选择整理数据，不通过模型分数猜测哪些轨迹值得训练。"""

    def __init__(self, artifacts: ArtifactStore):
        # 所有训练来源和环境快照都从同一份内容寻址材料中解析。
        self.artifacts = artifacts

    def feedback(self, usage: UsageRecord) -> dict:
        # 每条数据决定必须可追溯到审核人和其书面判断理由。
        feedback = self.artifacts.get(usage.feedback)
        if any(not isinstance(feedback.get(k), str) or not feedback[k].strip() for k in ("reviewer", "notes")):
            raise ValueError("Human feedback needs a reviewer and notes.")
        if type(feedback.get("regression", False)) is not bool:
            raise ValueError("Regression must be a boolean.")
        return feedback

    def regression(self, usage: UsageRecord) -> Task | None:
        # 只有人明确标记回归时才尝试构造新测试任务。
        if not self.feedback(usage).get("regression", False):
            return None
        task = usage.trace.task
        # 重新创建原始环境，用真实工具结果检查轨迹中的行动是否可复现。
        session = None
        try:
            self.artifacts.get(task.problem)
            events = self.artifacts.get(usage.trace.events)
            session = PaperEnvironment(self.artifacts).reset(task.initial_state, seed=task.seed)
            # 第一条观察必须和同 seed 的新环境一致。
            if not events or events[0].get("observation") != session.observe():
                return None
            # 顺序重放每次工具调用；返回值不一致说明证据不足以回归。
            for event in events:
                if "tool" in event and session.call(event["tool"], event["arguments"]) != event["result"]:
                    return None
        except (KeyError, TypeError, ValueError):
            # 不完整或无法解释的轨迹不丢掉原记录，只不生成回归题。
            return None
        finally:
            if session is not None:
                # 无论重放成功与否都释放会话。
                session.close()
        # 新题 ID 由来源任务内容生成；原 UsageRecord 继续保留完整出处。
        return replace(task, id="regression-" + self.artifacts.put(asdict(task)).ref[:16])

    def prepare(self, usage: UsageRecord) -> PreparedData:
        # training_steps 是审核者选中的模型调用序号，从零开始编号。
        feedback = self.feedback(usage)
        steps = feedback.get("training_steps", [])
        if not isinstance(steps, list) or any(type(i) is not int or i < 0 for i in steps):
            raise ValueError("Training steps must be zero-based model-call indices.")
        # 工具轨迹包含观察和动作；这里只筛出真实发给模型的调用事件。
        calls = [event for event in self.artifacts.get(usage.trace.events) if "model_input" in event]
        samples = []
        for index in sorted(set(steps)):
            if index >= len(calls):
                raise ValueError("Reviewed step is outside this trace.")
            call = calls[index]
            prompt, response = call.get("model_input"), call.get("model_output")
            if not isinstance(prompt, str) or not prompt.strip() or not isinstance(response, str):
                raise ValueError("Reviewed step lacks an input or completed response.")
            # 本例 Agent 的协议是 JSON 对象，先做语法检查再写入样本。
            if not isinstance(json.loads(response), dict):
                raise ValueError("This agent's training response must be a JSON object.")
            # 保留模型当时看到的完整历史，不能只留最后一轮导致上下文丢失。
            sample = self.artifacts.put({"messages": [
                {"role": "user", "content": prompt}, {"role": "assistant", "content": response}]})
            # 内容哈希可合并相同训练回合，避免重复样本。
            if sample not in samples:
                samples.append(sample)
        return PreparedData(usage, tuple(samples), feedback["notes"] if samples else "No steps selected by the reviewer.")


def load_regressions(artifacts: ArtifactStore, benchmark: Benchmark, path: Path) -> Benchmark:
    """Import reviewed tasks into a development benchmark; keep its tools and verifiers."""
    # 回归题只能加入开发集，且来源与目标环境需保持相同重放条件。
    manifest = artifacts.get(benchmark.definition)
    if manifest["split"] != "development":
        raise ValueError("Add regression tasks to development benchmarks only.")
    bundle = json.loads(path.read_text(encoding="utf-8"))
    # 先校验导入材料的内容哈希，防止任务引用被悄悄替换。
    artifacts.contents.update(ArtifactStore(bundle["artifacts"]).contents)
    source = artifacts.get(Artifact(bundle["source_benchmark"]))
    if source["environment"] != manifest["environment"] or source["tools"] != manifest["tools"]:
        raise ValueError("Replay tasks using the same environment and tool versions.")
    # 以问题、初始状态和 seed 判断是不是已经存在相同测试条件。
    tasks = list(benchmark.tasks)
    keys = {(task.problem, task.initial_state, task.seed) for task in tasks}
    for item in bundle["regression_tasks"]:
        task = read_task(item)
        key = (task.problem, task.initial_state, task.seed)
        if key not in keys:
            # 新条件才追加；重复任务不增加 Benchmark 规模。
            if any(existing.id == task.id for existing in tasks):
                raise ValueError("Conflicting regression task IDs.")
            tasks.append(task)
            keys.add(key)
    # 没有新任务时复用原 Benchmark 版本，避免制造空改动。
    if len(tasks) == len(benchmark.tasks):
        return benchmark
    # 新清单指回父版本并引用本批反馈材料，原有验证器保持不变。
    definition = artifacts.put({**manifest, "parent": benchmark.definition.ref,
                                "tasks": [asdict(task) for task in tasks],
                                "feedback": artifacts.put(bundle["records"]).ref})
    return replace(benchmark, definition=definition, tasks=tuple(tasks))


def main():
    """把评测报告与逐任务人工反馈转换成回归包和训练样本包。"""
    parser = argparse.ArgumentParser(description=__doc__)
    # 这两份输入分别提供机器轨迹和人工判断，结果只写入新文件。
    parser.add_argument("report", type=Path)
    parser.add_argument("reviews", type=Path, help="Human feedback keyed by task ID from this report")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Use a new output path.")
    # 还原评测和逐个任务的审核意见。
    report = json.loads(args.report.read_text(encoding="utf-8"))
    reviews = json.loads(args.reviews.read_text(encoding="utf-8"))
    # 恢复内容哈希仓库时会逐个核对引用是否对应实际内容。
    artifacts = ArtifactStore(report["artifacts"])
    source_benchmark = Artifact(**report["evaluation"]["benchmark"])
    # 训练和调优数据不能从封存测试集中抽取。
    if artifacts.get(source_benchmark)["split"] != "development":
        parser.error("Do not turn held-out test results into development or training data.")
    curator = PaperDataCurator(artifacts)
    # 按任务 ID 把人工反馈和对应的完整轨迹重新配对。
    cases = {case["trace"]["task"]["id"]: case["trace"] for case in report["evaluation"]["cases"]}
    records, tasks, samples = [], {}, {}
    # 逐条采纳明确审核，不自动把所有高分或低分轨迹变成数据。
    for task_id, review in reviews.items():
        item = cases[task_id]
        # 初始化或快照失败的轨迹可以没有终态，仍应保留执行和人工反馈。
        trace = Trace(read_task(item["task"]), *(Artifact(**item[key]) for key in
                                               ("agent", "events", "result")),
                      Artifact(**item["final_state"]) if item["final_state"] is not None else None)
        usage = UsageRecord(trace, artifacts.put(review))
        # 两个出口相互独立：同一用例可入回归集、训练集，或仅保留原记录。
        task = curator.regression(usage)
        data = curator.prepare(usage)
        reason = "Replay matched." if task else "Not requested."
        if review.get("regression") and task is None:
            reason = "Replay evidence was missing or did not match."
        records.append({"prepared": asdict(data), "regression": asdict(task) if task else None,
                        "regression_reason": reason})
        if task:
            # 按稳定任务 ID 收集经重放检查通过的回归题。
            tasks[task.id] = asdict(task)
        # 以样本引用去重，导出时使用普通 JSON 而不是内部编码字符串。
        samples.update({sample.ref: artifacts.get(sample) for sample in data.samples})
    # 独占创建输出文件，避免覆盖之前的审核材料。
    with args.out.open("x", encoding="utf-8") as output:
        json.dump({"source_benchmark": source_benchmark.ref,
                   "regression_tasks": list(tasks.values()), "training_samples": list(samples.values()),
                   "records": records, "artifacts": artifacts.contents}, output, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # 直接运行此文件时执行 CLI；作为模块导入时不读取文件或启动任务。
    main()
