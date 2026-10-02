"""Run one explicit paper-summary experiment and save its evidence."""
import argparse
import importlib
import json
from dataclasses import asdict
from pathlib import Path

from .agent import INSTRUCTION
from .artifacts import ArtifactStore
from .benchmark import PaperBenchmarkRunner, build_benchmark
from .data_feedback import load_regressions
from .rubric_calibration import PaperRubricEvaluator, PaperRubricOptimizer, calibrate_rubric
from .agent_evolution import PaperPromptOptimizer, evolve_agent
from .task_synthesis import PaperTaskSynthesizer, PaperTaskValidator, synthesize_tasks


def main():
    """解析参数并运行恰好一种改进实验；不在导入时访问模型。"""
    # argparse 负责给使用者清楚的必填参数和命令行错误。
    parser = argparse.ArgumentParser(description=__doc__)
    # 每次运行至少需要一篇实际论文和一个明确的阅读目标。
    parser.add_argument("papers", type=Path, nargs="+")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--model", required=True, help="Python module:function, accepting a prompt and returning text")
    parser.add_argument("--model-id", required=True, help="Model version and inference configuration identifier")
    parser.add_argument("--agent-prompt", type=Path, help="Explicitly load an agent prompt from a UTF-8 file")
    parser.add_argument("--rubric", type=Path, help="Explicitly load a reviewed rubric from a UTF-8 file")
    parser.add_argument("--regressions", type=Path, help="Add a reviewed data-feedback bundle before evaluation")
    parser.add_argument("--min-chars", type=int, default=200)
    parser.add_argument("--max-chars", type=int, default=1200)
    parser.add_argument("--max-steps", type=int, default=16)
    parser.add_argument("--seed", type=int, default=0)
    # 三种改进实验各自改变一个对象，因此不能在一次运行里混在一起。
    experiment = parser.add_mutually_exclusive_group()
    experiment.add_argument("--synthesize", type=int, default=0, help="Propose up to this many new tasks per round")
    experiment.add_argument("--evolve", type=int, default=0, help="Maximum agent prompt revisions on a fixed benchmark")
    experiment.add_argument("--calibrate-rubric", type=int, default=0, help="Maximum rubric revisions on fixed traces")
    parser.add_argument("--judge-repeats", type=int, default=3, help="Independent parallel judgments per trace")
    parser.add_argument("--synthesis-rounds", type=int, default=1, help="Bounded proposal/review/evaluation rounds")
    parser.add_argument("--out", type=Path, required=True, help="New JSON report file, including referenced artifacts")
    # 解析参数后立即验证预算和输出路径，避免开始昂贵调用后才发现错误。
    args = parser.parse_args()
    if (args.max_steps < 1 or min(args.synthesize, args.evolve, args.calibrate_rubric) < 0
            or args.synthesis_rounds < 1 or args.judge_repeats < 2 or args.out.exists()):
        parser.error("Use valid budgets and a new output path.")
    # 把用户提供的 module:function 解析成可注入的文本完成函数。
    module, name = args.model.split(":", 1)
    complete = getattr(importlib.import_module(module), name)
    # 本轮材料共用同一仓库，以引用保存每个配置、请求、响应和判断。
    artifacts = ArtifactStore()
    model = artifacts.put({"adapter": args.model, "model": args.model_id})
    # 可显式装入已审核提示词，否则使用示例基线提示词。
    instruction = args.agent_prompt.read_text(encoding="utf-8") if args.agent_prompt else INSTRUCTION
    if not instruction.strip():
        parser.error("The agent prompt must not be empty.")
    # Rubric 同样可从外部提供；None 表示使用示例附带初稿。
    rubric = artifacts.put(args.rubric.read_text(encoding="utf-8")) if args.rubric else None
    agent = artifacts.put({"model": model.ref, "prompt": instruction, "max_steps": args.max_steps})
    # 先把任务、环境、工具和验证器组装为固定 Benchmark。
    benchmark = build_benchmark(artifacts, args.papers, args.goal, model, complete,
                                min_chars=args.min_chars, max_chars=args.max_chars, seed=args.seed, rubric=rubric)
    if args.regressions:
        # 人工审核且可重放的线上回归题，在基线评测之前加入开发集。
        benchmark = load_regressions(artifacts, benchmark, args.regressions)
    # 所有实验都通过同一个执行入口记录任务轨迹并调用验证器。
    runner = PaperBenchmarkRunner(artifacts, complete)
    result = runner.run(agent, benchmark)
    rounds = []
    if args.synthesize:
        # 基线轨迹用来生成候选；新题审核通过后重测并反馈给下一轮。
        synthesizer = PaperTaskSynthesizer(artifacts, model, complete)
        validator = PaperTaskValidator(artifacts, model, complete)
        result, rounds = synthesize_tasks(runner, benchmark, result, synthesizer, validator,
                                          count=args.synthesize, rounds=args.synthesis_rounds)
    evolution_rounds, calibration = [], None
    if args.evolve:
        # Agent 实验只改提示词，保留当前 Benchmark 和评分标准。
        optimizer = PaperPromptOptimizer(artifacts, model, complete)
        result, evolution_rounds = evolve_agent(runner, benchmark, result, optimizer, rounds=args.evolve)
    if args.calibrate_rubric:
        # Rubric 实验固定已得到的轨迹，直接重复评判和修改评分标准。
        calibration = calibrate_rubric(result, PaperRubricOptimizer(artifacts, model, complete),
                                PaperRubricEvaluator(artifacts, model, complete),
                                rounds=args.calibrate_rubric, repeats=args.judge_repeats, rubric=rubric)
    # 汇总最终评测、各轮记录和内容材料，方便离线审核与复用。
    with args.out.open("x", encoding="utf-8") as report:
        json.dump({"evaluation": asdict(result), "synthesis_rounds": rounds,
                   "evolution_rounds": evolution_rounds, "rubric_calibration": calibration,
                   "artifacts": artifacts.contents},
                  report, ensure_ascii=False, indent=2)
    print(f"Saved {len(result.cases)} task results to {args.out}")


if __name__ == "__main__":
    # 只有模块作为程序启动时才执行命令行流程。
    main()
