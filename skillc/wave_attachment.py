"""Closed controller-owned wave-state mount (#621), never a host bind mount."""
from __future__ import annotations

import re
from dataclasses import dataclass

WAVE_ROOT = "/run/skillc-wave"


@dataclass(frozen=True)
class WaveAttachment:
    """Only named volumes from the wave controller's namespace may be mounted."""

    volume: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"skillc-wave-[a-f0-9]{32}-state", self.volume) is None:
            raise ValueError("wave state must name a controller-owned wave volume")

    def mount_args(self) -> list[str]:
        return ["--mount", f"type=volume,source={self.volume},target={WAVE_ROOT},volume-nocopy"]

    def environment(self) -> dict[str, str]:
        return {"FLOW_WAVE_MAILBOX_DIR": WAVE_ROOT, "FLOW_WAVE_REGISTRY_DIR": WAVE_ROOT}
