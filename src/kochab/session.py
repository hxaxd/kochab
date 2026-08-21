from __future__ import annotations

from pathlib import Path

from kochab.adapters.host import BoundHost, load_host
from kochab.core.tools import EvolveTools
from kochab.gate.holdout import GatedEvalPort, HoldoutGate
from kochab.state import KochabState


class Session:
    def __init__(self, host: BoundHost) -> None:
        self.host = host
        self.state = KochabState(host.state_dir)
        self.gate = HoldoutGate(
            eval_port=host.eval,
            holdout_ids=list(host.holdout_ids),
            baseline_path=host.state_dir / "gate-baseline.json",
        )
        self.gated_eval = GatedEvalPort(host.eval, host.holdout_ids)
        self.tools = EvolveTools(
            surface=host.surface,
            eval_port=self.gated_eval,
            traces=host.traces,
            gate=self.gate,
            state=self.state,
        )


def open_session(host_dir: Path, *, require_frozen: bool = False) -> Session:
    host = load_host(host_dir)
    host.prepare()
    if require_frozen:
        from kochab.onboarding import verify_frozen

        verify_frozen(host)
    session = Session(host)
    session.gate.capture_if_missing(host.surface.head())
    return session
