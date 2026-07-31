from __future__ import annotations

import io
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from kochab.local.state import State, git, rev


def export_pack(state: State, out: Path) -> Path:
    """Export the accepted tree, independently of any edits in the candidate."""
    state.check()
    accepted = rev(state, "refs/kochab/accepted")
    baseline = rev(state, "refs/kochab/baseline")
    out = out.resolve()
    if out.is_relative_to(state.host):
        raise ValueError("export outside the source skill folder")
    if out.exists():
        raise ValueError(f"export directory already exists; choose a new directory: {out}")
    archive = git(state, "archive", "--format=zip", accepted)
    patch = git(state, "diff", "--binary", baseline, accepted)
    out.mkdir(parents=True)
    skill = out / "skill"
    skill.mkdir()
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        bundle.extractall(skill)
        # ZipFile does not restore executable bits on extracted scripts.
        for entry in bundle.infolist():
            target = skill / entry.filename
            mode = entry.external_attr >> 16
            if mode and target.is_file():
                target.chmod(mode & 0o777)
    (out / "changes.diff").write_bytes(patch)
    shutil.copy2(state.dir / "journal.jsonl", out / "journal.jsonl")
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "host": str(state.host),
        "baseline": baseline,
        "accepted": accepted,
        "candidate": rev(state, accepted + "^{tree}"),
        "skill": "skill",
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return out
