"""Build the paper benchmark, then reset, run and verify each task."""
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from kochab.benchmark import Benchmark, run_benchmark
from kochab.records import Artifact, Evaluation, Task

from .agent import PaperAgent
from .artifacts import ArtifactStore
from .environment import TOOLS, PaperEnvironment
from .verifiers import FormatVerifier, RubricVerifier


class PaperAgentFactory:
    """将论文示例的配置和模型函数接入通用运行器。"""

    def __init__(self, artifacts: ArtifactStore, complete: Callable[[str], str]):
        self.artifacts, self.complete = artifacts, complete

    def create(self, definition: Artifact, record: Callable[[object], None]) -> PaperAgent:
        config = self.artifacts.get(definition)

        def recorded(prompt):
            # 原始调用连同异常一起留下；环境事件由核心运行器负责记录。
            event = {"model_input": prompt}
            try:
                event["model_output"] = self.complete(prompt)
                return event["model_output"]
            except Exception as exc:
                event["error"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                record(event)

        return PaperAgent(self.artifacts, recorded, config["max_steps"], config["prompt"])


class PaperBenchmarkRunner:
    """示例只负责装配，逐题执行、记录和验证复用 src 中的循环。"""

    def __init__(self, artifacts: ArtifactStore, complete: Callable[[str], str]):
        self.artifacts, self.complete = artifacts, complete

    def run(self, agent: Artifact, benchmark: Benchmark) -> Evaluation:
        return run_benchmark(agent, benchmark, agents=PaperAgentFactory(self.artifacts, self.complete),
                             artifacts=self.artifacts)


def build_benchmark(artifacts: ArtifactStore, papers: list[Path], goal: str,
                    judge: Artifact, complete: Callable[[str], str], *,
                    min_chars: int = 200, max_chars: int = 1200, seed: int = 0,
                    rubric: Artifact | None = None) -> Benchmark:
    """把论文文件组装为任务，并绑定本例环境、工具和两种验证器。"""
    # 先拒绝空任务、空目标和互相矛盾的长度限制。
    if not papers or not goal.strip() or not 1 <= min_chars <= max_chars:
        raise ValueError("Provide papers, a reading goal and valid character limits.")
    # 所有论文共享同一阅读目标和输出长度要求。
    problem = artifacts.put({"goal": goal, "min_chars": min_chars, "max_chars": max_chars})
    tasks = []
    for paper in papers:
        if paper.suffix.lower() == ".pdf":
            # PDF 解析只在需要时导入，纯文本示例无需额外运行时依赖。
            from pypdf import PdfReader  # Optional, only for PDF input.
            pages = [page.extract_text() or "" for page in PdfReader(paper).pages]
        else:
            # 文本按显式换页符分开，以便引文使用稳定的页码。
            pages = paper.read_text(encoding="utf-8").split("\f")
        # 将内容哈希固定，之后 reset 不再依赖源文件有没有被修改。
        initial = artifacts.put({"title": paper.stem, "pages": pages})
        # 任务 ID 同时带来源文件名和内容摘要，便于识别与避免内容冲突。
        tasks.append(Task(f"{paper.stem}-{initial.ref[:12]}", problem, initial, seed))
    # 绝大多数情况下会由内容摘要区分；仍做显式检查，防止截断后碰撞。
    if len({task.id for task in tasks}) != len(tasks):
        raise ValueError("Duplicate paper tasks.")
    # 可以使用人工审过的 Rubric；未提供时读取本示例附带的初稿。
    rubric = rubric or artifacts.put(Path(__file__).with_name("rubric.md").read_text(encoding="utf-8"))
    if not isinstance(artifacts.get(rubric), str) or not artifacts.get(rubric).strip():
        raise ValueError("Rubric must contain non-empty text.")
    # 将机械检查和语义评分分成两个验证器，避免混成一个总分。
    verifiers = (FormatVerifier(artifacts), RubricVerifier(artifacts, rubric, judge, complete))
    # 清单记录任务、工具和验证器版本；任何变化都会产生新的内容引用。
    definition = artifacts.put({
        "example": "paper-summary", "version": 1, "split": "development",
        "tasks": [asdict(task) for task in tasks], "environment": "paper-session-v1",
        "tools": [asdict(tool) for tool in TOOLS],
        "verifiers": [v.definition.ref for v in verifiers],
        "reporting": "per-case deterministic checks and rubric dimensions, reported separately",
    })
    return Benchmark(definition, tuple(tasks), PaperEnvironment(artifacts), TOOLS, verifiers)


def require_development_evaluation(artifacts: ArtifactStore, evaluation: Evaluation):
    """要求输入是开发集全部任务的完整评测，防止选择流程误用测试集。"""
    # 从清单取预期任务，再逐项对照实际结果而不是只检查样本数。
    manifest = artifacts.get(evaluation.benchmark)
    tasks = [asdict(case.trace.task) for case in evaluation.cases]
    # Agent 版本必须与 Evaluation 标记一致，且任务不可重放重复或被遗漏。
    if (manifest.get("split") != "development" or not tasks
            or tasks != manifest.get("tasks") or len({t["id"] for t in tasks}) != len(tasks)
            or any(case.trace.agent != evaluation.agent for case in evaluation.cases)):
        raise ValueError("Use a complete evaluation of this development benchmark and agent.")

