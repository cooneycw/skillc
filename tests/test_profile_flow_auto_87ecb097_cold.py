"""Opt-in bounded cold proof; source installation happens only inside Docker.

Run the physical test explicitly with SKILLC_FLOW_AUTO_COLD=1 after obtaining
its serialized Docker slot. Default skips are not cold evidence. Script mode
is the trusted in-container actor, never an arbitrary candidate executor.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

CASES = ("source-valid-closure", "source-missing-dependency", "cold-install-clean",
         "cold-sibling-route", "cold-content-drift", "cold-mode-drift", "cold-offline-runner",
         "cold-cache-unavailable", "cold-forbidden-mount", "cold-review-evidence-absent")
LIMIT = 1024 * 1024


def need(value: Any, reason: str) -> None:
    if not value:
        raise RuntimeError(reason)


def settings(info: dict[str, Any], synthetic: bool = False) -> None:
    host = info["HostConfig"]
    need(host["NetworkMode"] == "none" and host["ReadonlyRootfs"], "network/root boundary")
    need(host["Memory"] == host["MemorySwap"] == 512 * LIMIT, "memory+swap boundary")
    need(host["NanoCpus"] == 1_000_000_000 and host["PidsLimit"] == 128, "CPU/pids boundary")
    need(host["Tmpfs"] == {"/home/proof": "rw,size=256m", "/work": "rw,size=256m",
                          "/project": "rw,size=32m", "/tmp": "rw,size=64m"}, "tmpfs boundary")
    binds = [m for m in info["Mounts"] if m["Type"] == "bind"]
    need(not binds, "forbidden bind" if synthetic else "unexpected operator bind")


class Budget:
    def __init__(self, root: Path, seconds: float = 1800) -> None:
        self.root, self.deadline = root, time.monotonic() + seconds
        self.used, self.calls = 0, 0
        self.events: list[dict[str, Any]] = []

    def check(self) -> None:
        need(time.monotonic() < self.deadline, "whole cold proof deadline")
        self.used = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        need(self.used <= 64 * LIMIT, "parent retained/staged bytes")

    def publish(self, path: Path, report: dict[str, Any]) -> None:
        payload = json.dumps(report, indent=2) + "\n"
        self.check()
        staged = path.with_suffix(".pending")
        staged.write_text(payload)
        try:
            self.check()
            staged.replace(path)
            self.check()
        except BaseException:
            path.write_text('{"status":"UNKNOWN; publication incomplete"}\n')
            raise

    def command(self, argv: list[str], cap: float = 30, cleanup: bool = False,
                cwd: Path | None = None, env: dict[str, str] | None = None) -> tuple[int, str, str]:
        if not cleanup:
            self.check()
        remaining = min(cap, 30 if cleanup else self.deadline - time.monotonic())
        need(remaining > 0, "no launch after expiry")
        self.calls += 1
        paths = [self.root / f"command-{self.calls}.{s}" for s in ("out", "err")]
        launcher = "import resource,os,sys;resource.setrlimit(resource.RLIMIT_FSIZE,(int(sys.argv[1]),)*2);os.execvp(sys.argv[2],sys.argv[2:])"
        with paths[0].open("xb") as out, paths[1].open("xb") as err:
            p = subprocess.Popen([sys.executable, "-c", launcher, str(LIMIT), *argv],
                                 cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
            try:
                p.wait(timeout=remaining)
            except BaseException:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait(timeout=2)
                raise
        sizes = [p.stat().st_size for p in paths]
        self.events.append({"command": argv[0:2], "returncode": p.returncode, "stream_bytes": sizes})
        need(all(n < LIMIT for n in sizes), "command output limit")
        if not cleanup:
            self.check()
        return p.returncode, paths[0].read_text(), paths[1].read_text()


# Everything below actor() runs inside the isolated disposable container.
def actor(case: str) -> dict[str, Any]:
    from skillc import profile
    source = Path("/opt/controller/tests/fixtures/profile-cpp-codex-flow-auto-87ecb097")
    decl = Path("/opt/controller/evals/subjects/cpp-codex-flow-auto-87ecb097/profile.json")
    inv = profile.validate(profile.Profile.load(decl), profile.DirTree(source))
    home = Path("/home/proof")
    receipt = profile.install(inv, profile.DirTree(source), home)
    verified = profile.verify_installed(inv, home)
    need(len(verified["files"]) == 121 and all(r["status"] == "satisfied" for r in verified["files"]),
         "actual installed surface")
    observations: list[Any] = [{"installed_files": len(verified["files"]), "receipt": receipt}]
    logs = Path("/work/commands")
    logs.mkdir()
    case_budget = Budget(logs, 55)
    def call(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> tuple[int, str]:
        rc, out, err = case_budget.command(argv, cwd=cwd, env=env)
        observations.append({"command": argv[:2], "rc": rc, "output": out + err})
        return rc, out + err
    project = Path("/project/repo")
    project.mkdir()
    for args in (["init", "-q", "-b", "issue-42-cold"], ["config", "user.name", "fixture"],
                 ["config", "user.email", "fixture@example.invalid"]):
        need(call(["git", *args], project)[0] == 0, "tiny Git setup")
    (project / "seed").write_text("owned fixture\n")
    need(call(["git", "add", "seed"], project)[0] == 0, "seed add")
    need(call(["git", "commit", "-qm", "seed"], project)[0] == 0, "seed commit")
    preferred = home / ".claude/scripts"
    bundled = home / ".codex/skills/flow-auto/scripts"
    if case == "cold-sibling-route":
        for directory in (preferred, bundled):
            rc, text = call(["bash", str(directory / "flow-start-resolve.sh"), "--verify", "42", "issue-42-cold"], project)
            need(rc == 0 and ("STASH_GUARD=current" in text or "STASH_GUARD=installed" in text), "actual sibling positive")
            guard = directory / "stash-worktree-guard.sh"
            original = guard.read_bytes()
            guard.unlink()
            rc, text = call(["bash", str(directory / "flow-start-resolve.sh"), "--verify", "42", "issue-42-cold"], project)
            need(rc == 0 and "STASH_GUARD=unknown" in text, "actual missing sibling negative")
            guard.write_bytes(original)
            guard.chmod(0o755)
    elif case in ("cold-content-drift", "cold-mode-drift"):
        target = preferred / "flow-start-resolve.sh"
        if case == "cold-content-drift":
            target.write_bytes(target.read_bytes() + b"\n# actual installed drift\n")
        else:
            target.chmod(0o644)
        rows = profile.verify_installed(inv, home)["files"]
        need(any(r["status"] == "violated" for r in rows), "installed drift refused")
        observations.append({"drift": rows})
    elif case in ("cold-offline-runner", "cold-cache-unavailable"):
        checkout = home / "Projects/claude-power-pack"
        marker = Path("/opt/cache-lock.sha256")
        actual = hashlib.sha256((checkout / "uv.lock").read_bytes()).hexdigest()
        if case == "cold-cache-unavailable":
            need(not marker.exists(), "uncached marker unexpectedly exists")
        else:
            def lock_check(observed: str) -> None:
                need(observed == actual, "baked/installed lock mismatch")
            lock_check(marker.read_text().strip())
            try:
                lock_check("0" * 64)
            except RuntimeError as exc:
                need(str(exc) == "baked/installed lock mismatch", "stale lock cause")
                observations.append({"stale_lock": "REFUSED before package resolution"})
            else:
                raise RuntimeError("stale lock classifier blind")
            shutil.copytree("/opt/cache", "/work/cache")
        env = {**os.environ, "UV_CACHE_DIR": "/work/cache", "UV_PROJECT_ENVIRONMENT": "/work/venv"}
        rc, text = call(["uv", "sync", "--locked", "--offline", "--no-install-project"], checkout, env)
        if case == "cold-cache-unavailable":
            need(rc != 0 and ("wasn't found in the cache" in text or "not found in the cache" in text), "specific offline-cache refusal")

        else:
            need(rc == 0, "offline dependency setup")
            env["PYTHONPATH"] = str(checkout)
            python = "/work/venv/bin/python"
            need(call([python, "-c", "import lib.cicd,lib.security"], project, env)[0] == 0, "offline imports")
            (project / "Makefile").write_text("test:\n\tpython3 -m unittest discover -s tests -v\n")
            (project / "tests").mkdir()
            test = project / "tests/test_active.py"
            test.write_text("import unittest\nclass Active(unittest.TestCase):\n def test_active(self): self.assertTrue(True)\n")
            for passing in (True, False):
                if not passing:
                    test.write_text(test.read_text().replace("assertTrue(True)", "assertTrue(False)"))
                rc, text = call([python, "-m", "lib.cicd", "run", "--plan", "check", "--path", str(project)], project, env)
                need((rc == 0) == passing, "real check-plan active/failing twin")
    elif case == "cold-review-evidence-absent":
        (project / "docs/measurements/counter-model").mkdir(parents=True)
        rc, text = call(["bash", str(preferred / "flow-finish-gate.sh"), "--enrolment-only"], project)
        need(rc != 0 and ("receipt" in text or "enrol" in text), "actual enrollment refusal")
        # Real writer: missing reviewer and then missing implementer; no invented evidence.
        rc, text = call([sys.executable, str(preferred / "counter-model-receipt.py"), "write",
                         "--issue", "42", "--branch", "issue-42-cold", "--status", "ran"], project)
        need(rc != 0 and "reviewer" in text, "missing reviewer refusal")
        rc, text = call([sys.executable, str(preferred / "counter-model-receipt.py"), "write",
                         "--issue", "42", "--branch", "issue-42-cold", "--status", "skipped",
                         "--reason", "reviewer-unavailable"], project)
        need(rc != 0 and "missing implementer identity" in text
             and not list((project / "docs/measurements/counter-model").glob("*.json")), "missing implementer refusal")
    return {"case": case, "observations": observations, "scope": "cold commands only; full flow UNPROVEN"}


def cold_proof(tmp: Path) -> dict[str, Any]:
    import test_profile_flow_auto_87ecb097 as spec
    budget = Budget(tmp)
    nonce = uuid.uuid4().hex
    containers: list[str] = []
    images: list[str] = []
    tags: list[str] = []
    rows: list[dict[str, Any]] = []
    cleanup: list[Any] = []
    context = tmp / "context"
    context.mkdir()
    try:
        # Only exact committed public inputs, no arbitrary checkout copy.
        paths = ["skillc", "tests/test_profile_flow_auto_87ecb097.py", __file__,
                 "tests/fixtures/profile-cpp-codex-flow-auto-87ecb097",
                 "evals/subjects/cpp-codex-flow-auto-87ecb097", "docker/profile-flow-auto-568/Dockerfile"]
        paths[2] = str(Path(__file__).relative_to(spec.ROOT))
        for name in paths:
            rc, out, _ = budget.command(["git", "status", "--porcelain", "--", name])
            need(rc == 0 and not out, "build source must be committed and clean")
        archive = tmp / "context.tar"
        with archive.open("wb") as archive_stream:
            subprocess.run(["git", "archive", "HEAD", *paths], stdout=archive_stream, check=True, timeout=30)
        budget.check()
        import tarfile
        with tarfile.open(archive) as tar:
            tar.extractall(context, filter="data")
        for name in paths:
            original = spec.ROOT / name
            items = original.rglob("*") if original.is_dir() else [original]
            for p in items:
                if p.is_file():
                    need((context / p.relative_to(spec.ROOT)).read_bytes() == p.read_bytes(), "export source identity")
        for target in ("cached", "uncached"):
            tag = f"skillc-b3a-{nonce}:{target}"
            tags.append(tag)
            rc, _, err = budget.command(["docker", "build", "--target", target, "--label", f"skillc.b3a={nonce}",
                                        "-t", tag, "-f", str(context / "docker/profile-flow-auto-568/Dockerfile"), str(context)], 300)
            need(rc == 0, "purpose image build unavailable: " + err[-500:])
            rc, output, _ = budget.command(["docker", "image", "inspect", tag])
            info = json.loads(output)[0]
            need(rc == 0 and info["Config"]["Labels"]["skillc.b3a"] == nonce, "owned image identity")
            images.append(info["Id"])
        spec.check_source()
        inv, tree = spec.inventory()
        need(len(spec.profile.installed_home_files(inv, tree)) == 121, "normal source closure")
        rows.append({"case": CASES[0], "source_files": 388, "installed_plan": 121})
        raw = json.loads(spec.DECLARATION.read_text())
        raw["dependencies"] = [d for d in raw["dependencies"] if d["id"] != "helper-gate-lib"]
        try:
            spec.profile.validate(spec.profile.Profile.from_dict(raw, spec.DECLARATION.parent), tree)
        except spec.profile.Refused:
            rows.append({"case": CASES[1], "negative": "normal validator REFUSED"})
        else:
            raise RuntimeError("missing dependency accepted")
        for case in CASES[2:]:
            case_end = min(budget.deadline, time.monotonic() + 60)
            name = f"skillc-b3a-{nonce}-{len(containers)}"
            containers.append(name)  # Ownership name recorded BEFORE daemon allocation.
            cmd = ["docker", "create", "--name", name, "--label", f"skillc.b3a={nonce}", "--network", "none",
                   "--read-only", "--memory", "512m", "--memory-swap", "512m", "--cpus", "1", "--pids-limit", "128",
                   "--tmpfs", "/home/proof:rw,size=256m", "--tmpfs", "/work:rw,size=256m",
                   "--tmpfs", "/project:rw,size=32m", "--tmpfs", "/tmp:rw,size=64m", "-e", "HOME=/home/proof"]
            forbidden = case == "cold-forbidden-mount"
            if forbidden:
                sentinel = tmp / "sentinel"
                sentinel.write_text("owned synthetic control only")
                cmd += ["--mount", f"type=bind,source={sentinel},target=/sentinel,readonly"]
            cmd += [images[int(case == "cold-cache-unavailable")], "python", "/opt/controller/tests/" + Path(__file__).name, case]
            rc, output, _ = budget.command(cmd, min(30, case_end - time.monotonic()))
            need(rc == 0 and output.strip(), "container allocation")
            rc, output, _ = budget.command(["docker", "inspect", name], min(30, case_end - time.monotonic()))
            info = json.loads(output)[0]
            need(info["Config"]["Labels"]["skillc.b3a"] == nonce, "container ownership")
            if forbidden:
                try:
                    settings(info, True)
                except RuntimeError as exc:
                    need(str(exc) == "forbidden bind", "unrelated containment error")
                else:
                    raise RuntimeError("bind classifier blind")
                rows.append({"case": case, "negative": "actual synthetic bind REFUSED"})
                continue
            settings(info)
            rc, output, err = budget.command(["docker", "start", "-a", name], min(60, case_end - time.monotonic()))
            need(rc == 0, "actor unavailable: " + err[-1000:] + output[-1000:])
            row = json.loads(output)
            need(row["case"] == case and time.monotonic() < case_end, "case identity/deadline")
            rows.append(row)
    finally:
        for name in reversed(containers):
            rc, out, err = budget.command(["docker", "inspect", name], cleanup=True)
            if rc:
                need("No such" in err, "cannot establish owned container absence")
                cleanup.append({"container": name, "absent": True})
                continue
            need(json.loads(out)[0]["Config"]["Labels"]["skillc.b3a"] == nonce, "refuse foreign cleanup")
            need(budget.command(["docker", "rm", "-f", name], cleanup=True)[0] == 0, "container cleanup")
            rc, _, err = budget.command(["docker", "inspect", name], cleanup=True)
            need(rc != 0 and "No such" in err, "container absence unconfirmed")
            cleanup.append({"container": name, "absent": True})
        for tag in reversed(tags):
            rc, out, err = budget.command(["docker", "image", "inspect", tag], cleanup=True)
            if rc:
                need("No such" in err, "owned image state unavailable")
                continue
            need(json.loads(out)[0]["Config"]["Labels"]["skillc.b3a"] == nonce, "refuse foreign image cleanup")
            need(budget.command(["docker", "image", "rm", tag], cleanup=True)[0] == 0, "owned image tag cleanup")
    budget.check()
    for row in rows:
        row["executed_substeps"] = len(row.get("observations", []))
    need([r["case"] for r in rows] == list(CASES), "cold expected/executed population")
    report = {"cases": rows, "cleanup": cleanup, "commands": budget.events,
              "parent_bytes": budget.used, "status": "BOUNDED COLD PROOF; full flow UNPROVEN"}
    budget.publish(tmp / "cold-report.json", report)
    return report


if __name__ == "__main__":
    need(len(sys.argv) == 2 and sys.argv[1] in CASES, "closed cold actor")
    print(json.dumps(actor(sys.argv[1])))
else:
    import pytest

    @pytest.mark.real_docker
    @pytest.mark.xdist_group(name="real_docker")
    @pytest.mark.timeout(1900)
    @pytest.mark.skipif(os.environ.get("SKILLC_FLOW_AUTO_COLD") != "1", reason="opt-in physical cold proof requires serialized Docker slot")
    def test_actual_cold_profile(tmp_path: Path) -> None:
        try:
            report = cold_proof(tmp_path)
            need(len(report["cases"]) == 10, "physical population")
        except BaseException as exc:
            (tmp_path / "cold-failure.json").write_text(json.dumps({"status": "UNKNOWN", "reason": str(exc)}) + "\n")
            raise

    @pytest.mark.parametrize("fault", ["network", "memory", "swap", "cpu", "pids", "tmpfs", "bind"])
    def test_containment_classifier_has_positive_and_negative(tmp_path: Path, fault: str) -> None:
        info: dict[str, Any] = {"HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True,
            "Memory": 512 * LIMIT, "MemorySwap": 512 * LIMIT, "NanoCpus": 1_000_000_000,
            "PidsLimit": 128, "Tmpfs": {"/home/proof": "rw,size=256m", "/work": "rw,size=256m",
                                      "/project": "rw,size=32m", "/tmp": "rw,size=64m"}}, "Mounts": []}
        settings(info)
        field = {"network": "NetworkMode", "memory": "Memory", "swap": "MemorySwap",
                 "cpu": "NanoCpus", "pids": "PidsLimit", "tmpfs": "Tmpfs"}.get(fault)
        if field:
            del info["HostConfig"][field]
        else:
            info["Mounts"] = [{"Type": "bind", "Source": str(tmp_path / "synthetic") }]
        with pytest.raises((RuntimeError, KeyError)):
            settings(info)

    @pytest.mark.parametrize("fault", ["stdout", "stderr", "timeout", "expired"])
    def test_command_budget_has_discriminating_inputs(tmp_path: Path, fault: str) -> None:
        budget = Budget(tmp_path, 5)
        assert budget.command([sys.executable, "-c", "print('healthy')"])[0] == 0
        if fault == "expired":
            budget.deadline = time.monotonic() - 1
            calls = budget.calls
            with pytest.raises(RuntimeError, match="whole cold proof deadline"):
                budget.command([sys.executable, "-c", "pass"])
            assert budget.calls == calls
        elif fault == "timeout":
            with pytest.raises(subprocess.TimeoutExpired):
                budget.command([sys.executable, "-c", "import time;time.sleep(60)"], 0.05)
        else:
            fd = 1 if fault == "stdout" else 2
            with pytest.raises(RuntimeError, match="output limit"):
                budget.command([sys.executable, "-c", f"import os;os.write({fd},b'x'*{LIMIT});os.write({fd},b'y')"])

    def test_publication_rechecks_after_serialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        budget = Budget(tmp_path)
        target = tmp_path / "report.json"
        budget.publish(target, {"status": "healthy"})
        target.unlink()
        dumps = json.dumps
        def late(*args: Any, **kwargs: Any) -> str:
            value = dumps(*args, **kwargs)
            budget.deadline = time.monotonic() - 1
            return value
        monkeypatch.setattr(json, "dumps", late)
        with pytest.raises(RuntimeError, match="whole cold proof deadline"):
            budget.publish(target, {"status": "must not publish"})
        assert not target.exists()
