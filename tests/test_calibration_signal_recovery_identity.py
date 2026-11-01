"""No-daemon consumer regression for the live probe's frozen image identity."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import test_calibration_signal_recovery_live as live


@pytest.mark.parametrize("retagged", [False, True], ids=["stable-tag", "tag-drift"])
def test_probe_launch_remains_bound_to_resolved_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retagged: bool,
) -> None:
    tag = "skillc-trial:signal-identity-control"
    frozen = "sha256:" + "a" * 64
    replacement = "sha256:" + "b" * 64
    registry = {frozen: frozen, tag: replacement if retagged else frozen}
    launches: list[str] = []

    def execute_script(backend: Any, *_args: object, **_kwargs: object) -> dict[str, object]:
        # Inspect the actual Docker run composition from the backend the
        # real controller supplied, after the tag has changed in this registry.
        argv = backend._keepalive_run_argv("identity-probe", "identity-probe")
        launched = argv[argv.index("--") + 1]
        launches.append(launched)
        assert registry[launched] == frozen, "tag drift changed the launched image"
        assert backend.network == "none"
        return {"disposition": "captured"}

    def schedule(declaration: Any, **_kwargs: object) -> None:
        assert declaration.shared["image"] == {"tag": tag, "digest": frozen}
        injected_attempt: Any = live.cc.run_level1_agent_attempt
        injected_attempt(
            experiment=object(), attempt_id="identity-probe", completion_deadline=None)

    # Only expensive schedule/lifecycle boundaries are replaced. The actual
    # live controller chooses and constructs its real DockerBackend subclass.
    monkeypatch.setattr(live.cc, "run_level1_agent_attempt", live.cc.run_level1_agent_attempt)
    monkeypatch.setattr(live.lifecycle, "run_through_backend", execute_script)
    monkeypatch.setattr(live.cr, "run_calibration", schedule)
    assert live._controller(tmp_path, "after-dispatch", tag, frozen) == 0
    assert len(launches) == 1
