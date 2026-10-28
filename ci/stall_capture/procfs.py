"""Parsers for the kernel interfaces both samplers read (#484). Pure functions
over text, so every one of them is exercised against a committed fake tree.

Nothing here opens a file for writing or runs a command: the samplers are
read-only by construction, and this is the whole of what they read."""

from __future__ import annotations

from pathlib import Path

#: /proc/diskstats columns after `major minor name` (Documentation/admin-guide/iostats.rst).
DISKSTAT_FIELDS = ("reads", "reads_merged", "read_sectors", "read_ms", "writes", "writes_merged",
                   "write_sectors", "write_ms", "in_flight", "io_ms", "weighted_io_ms",
                   "discards", "discards_merged", "discard_sectors", "discard_ms")
SECTOR_BYTES = 512


class Unreadable(Exception):
    """An interface the sample needs is absent or does not parse. Raised, never
    defaulted to zero: a zero here would read as a quiet system."""


def read(root: Path, path: str) -> str:
    try:
        return (root / path.lstrip("/")).read_text(encoding="utf-8")
    except OSError as exc:
        raise Unreadable(f"{path}: {exc.strerror or exc}") from None


def parse_psi(text: str) -> dict[str, dict[str, float]]:
    """`/proc/pressure/<resource>` or a cgroup's `<resource>.pressure`."""
    out: dict[str, dict[str, float]] = {}
    for line in text.splitlines():
        kind, _, rest = line.partition(" ")
        if kind not in ("some", "full"):
            continue
        try:
            out[kind] = {k: float(v) for k, v in (f.split("=", 1) for f in rest.split())}
        except ValueError:
            raise Unreadable(f"pressure line does not parse: {line!r}") from None
    if "some" not in out or "avg10" not in out["some"]:
        raise Unreadable("pressure text has no 'some avg10'")
    return out


def parse_diskstats(text: str, devices: list[str]) -> dict[str, dict[str, int]]:
    """The named devices' cumulative counters. A device that is not listed is
    an error, not an empty entry."""
    found: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        cols = line.split()
        if len(cols) >= 3 + len(DISKSTAT_FIELDS) and cols[2] in devices:
            found[cols[2]] = dict(zip(DISKSTAT_FIELDS, (int(c) for c in cols[3:3 + len(DISKSTAT_FIELDS)]),
                                      strict=True))
    missing = [d for d in devices if d not in found]
    if missing:
        raise Unreadable(f"diskstats has no line (with discard columns) for {missing}")
    return found


def parse_cpu_ticks(text: str) -> dict[str, int]:
    """The aggregate `cpu` line of /proc/stat: steal and the total it is a share of.
    guest time is already counted inside user, so it is not added again."""
    for line in text.splitlines():
        cols = line.split()
        if cols and cols[0] == "cpu":
            ticks = [int(c) for c in cols[1:9]]
            if len(ticks) < 8:
                break
            return {"total": sum(ticks), "steal": ticks[7], "iowait": ticks[4]}
    raise Unreadable("/proc/stat has no aggregate cpu line with a steal column")


def parse_keyed(text: str) -> dict[str, int]:
    """A flat `key value` file such as a cgroup's `cpu.stat`."""
    out: dict[str, int] = {}
    for line in text.splitlines():
        cols = line.split()
        if len(cols) == 2 and cols[1].lstrip("-").isdigit():
            out[cols[0]] = int(cols[1])
    return out


def parse_io_stat(text: str) -> dict[str, int]:
    """A cgroup's `io.stat`, summed over its devices."""
    total = {"rbytes": 0, "wbytes": 0, "rios": 0, "wios": 0, "dbytes": 0, "dios": 0}
    for line in text.splitlines():
        for field in line.split()[1:]:
            key, _, value = field.partition("=")
            if key in total and value.isdigit():
                total[key] += int(value)
    return total
