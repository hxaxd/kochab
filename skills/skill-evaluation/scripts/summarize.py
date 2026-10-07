"""Summarize recorded skill evaluations without starting model runs."""
import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path


def measured(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def stats(values):
    values = [v for v in values if measured(v)]
    if not values:
        return None
    return {'mean': statistics.mean(values), 'stddev': statistics.stdev(values) if len(values) > 1 else 0,
            'min': min(values), 'max': max(values), 'observations': len(values)}


def summarize(workspace, skill_name):
    runs = []
    notes = []
    for case in sorted(workspace.glob('eval-*')):
        meta_path = case / 'eval_metadata.json'
        meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
        for condition in sorted(p for p in case.iterdir() if p.is_dir()):
            for run in sorted(condition.glob('run-*')):
                grade_path = run / 'grading.json'
                if not grade_path.exists():
                    notes.append(f'{run.relative_to(workspace)}: 未提供评分，未计入通过率')
                    continue
                grade = json.loads(grade_path.read_text(encoding='utf-8'))
                status = grade.get('status', 'completed')
                if status not in {'completed', 'failed', 'not_run'}:
                    raise ValueError(f'Invalid status: {grade_path}')
                expectations = grade.get('expectations', [])
                if not isinstance(expectations, list):
                    raise ValueError(f'Invalid expectations: {grade_path}')
                for expectation in expectations:
                    if not isinstance(expectation, dict) or not isinstance(expectation.get('text'), str):
                        raise ValueError(f'Invalid expectation: {grade_path}')
                    if expectation.get('passed') is not None and type(expectation['passed']) is not bool:
                        raise ValueError(f'Invalid verdict: {grade_path}')
                    if not isinstance(expectation.get('evidence'), str) or not expectation['evidence'].strip():
                        raise ValueError(f'Missing evidence: {grade_path}')
                passed = sum(e.get('passed') is True for e in expectations)
                failed = sum(e.get('passed') is False for e in expectations)
                unknown = len(expectations) - passed - failed
                total = len(expectations)
                rate = passed / total if status == 'completed' and total else None
                timing_path = run / 'timing.json'
                timing = json.loads(timing_path.read_text(encoding='utf-8')) if timing_path.exists() else {}
                result = {'status': status, 'pass_rate': rate, 'passed': passed, 'failed': failed,
                          'unknown': unknown, 'total': total}
                for field, source in [('time_seconds', 'total_duration_seconds'), ('tokens', 'total_tokens')]:
                    value = timing.get(source)
                    if measured(value):
                        result[field] = value
                runs.append({'eval_id': meta.get('eval_id', case.name), 'eval_name': meta.get('eval_name', case.name),
                             'configuration': condition.name, 'run_number': run.name[4:], 'result': result,
                             'expectations': expectations})
                if unknown or status != 'completed':
                    notes.append(f'{run.relative_to(workspace)}: 状态 {status}，未知条件 {unknown}')
    summary = {}
    for condition in sorted({r['configuration'] for r in runs}):
        selected = [r['result'] for r in runs if r['configuration'] == condition]
        summary[condition] = {metric: stats([r.get(metric) for r in selected])
                              for metric in ['pass_rate', 'time_seconds', 'tokens']}
        summary[condition]['recorded_runs'] = len(selected)
        summary[condition]['completed_runs'] = sum(r['status'] == 'completed' for r in selected)
    primary = 'with_skill' if 'with_skill' in summary else None
    baseline = next((c for c in ['without_skill', 'old_skill'] if c in summary), None)
    delta = {}
    if primary and baseline:
        for metric in ['pass_rate', 'time_seconds', 'tokens']:
            a, b = summary[primary][metric], summary[baseline][metric]
            if a and b:
                diff = a['mean'] - b['mean']
                delta[metric] = f'{diff:+.4f}'
                if metric == 'pass_rate':
                    delta[metric] = f'{diff*100:+.1f} pp'
    summary['delta'] = delta
    return {'metadata': {'skill_name': skill_name, 'generated_at': datetime.now(timezone.utc).isoformat(),
                         'evals_run': sorted({str(r['eval_id']) for r in runs}),
                         'recorded_runs': len(runs)}, 'run_summary': summary, 'runs': runs, 'notes': notes}


def markdown(data):
    lines = [f"# {data['metadata']['skill_name']} 评测汇总", '',
             '基于已有记录；此脚本不运行模型。未知指标以“未知”表示。', '',
             '| 条件 | 记录数 | 已完成 | 通过率均值 | 耗时均值（秒） | 模型用量均值 |',
             '| --- | --- | --- | --- | --- | --- |']
    for name, values in data['run_summary'].items():
        if name == 'delta':
            continue
        def display(metric, percentage=False):
            stat = values[metric]
            if not stat:
                return '未知'
            value = stat['mean'] * (100 if percentage else 1)
            return f'{value:.2f}' + ('%' if percentage else '')
        lines.append(f"| {name} | {values['recorded_runs']} | {values['completed_runs']} | {display('pass_rate', True)} | {display('time_seconds')} | {display('tokens')} |")
    lines.extend(['', '需结合样本覆盖、输入与运行条件判断可比性，汇总数值本身不证明收益。', ''])
    lines.extend('- ' + n for n in data['notes'])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('--skill-name', default='技能')
    args = parser.parse_args()
    if not args.workspace.is_dir():
        parser.error('workspace must be an existing directory')
    data = summarize(args.workspace, args.skill_name)
    (args.workspace / 'benchmark.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.workspace / 'benchmark.md').write_text(markdown(data), encoding='utf-8')
    print(f"Summarized {len(data['runs'])} recorded runs")


if __name__ == '__main__':
    main()
