from __future__ import annotations

import sys
from pathlib import Path

from kochab.adapters.eval_cli import CliEvalPort
from kochab.adapters.files import FileSurface
from kochab.contracts.models import UnitManifest


def test_cli_eval_collects_newest_result_and_isolates_holdout_env(tmp_path: Path) -> None:
    (tmp_path / "surface").mkdir()
    (tmp_path / "surface" / "SYSTEM.md").write_text("prompt\n", encoding="utf-8")
    script = tmp_path / "eval.py"
    script.write_text(
        """import argparse, json, os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--result-dir')
parser.add_argument('--cases')
args = parser.parse_args()
root = Path(args.result_dir)
old = root / 'old.json'
new = root / 'new.json'
payload = {
    'score': 0.5 if os.environ.get('KOCHAB_EVAL_VISIBILITY') == 'holdout' else 1.0,
    'passed': True,
    'metrics': {'otel_disabled': int(os.environ.get('OTEL_SDK_DISABLED') == 'true')},
    'cases': [{'id': item, 'score': 1.0, 'passed': True, 'feedback': ''}
              for item in args.cases.split(',') if item],
}
old.write_text(json.dumps({'score': 0, 'passed': False, 'cases': []}), encoding='utf-8')
new.write_text(json.dumps(payload), encoding='utf-8')
os.utime(old, (1, 1))
os.utime(new, (2, 2))
""",
        encoding="utf-8",
    )
    surface = FileSurface(
        tmp_path / ".state" / "work",
        [UnitManifest(id="system", category="knowledge", path="surface/SYSTEM.md")],
        tmp_path,
    )
    version = surface.bootstrap()
    port = CliEvalPort(
        host_root=tmp_path,
        command=[sys.executable, "eval.py"],
        list_args=[],
        run_args=["--result-dir", "{result_dir}", "--cases", "{case_ids}"],
        surface=surface,
        result_glob="*.json",
    )

    result = port.run(["hidden-a"], version, visibility="holdout")

    assert result.score == 0.5
    assert result.passed is True
    assert result.cases[0].id == "hidden-a"
    assert result.metrics["otel_disabled"] == 1
