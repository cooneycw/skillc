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
EXPECTED_SUBSTEPS = dict(zip(CASES, (1, 1, 7, 13, 7, 7, 11, 7, 1, 9), strict=True))
LIMIT = 1024 * 1024


def need(value: Any, reason: str) -> None:
    if not value:
        raise RuntimeError(reason)


def case_population(rows: list[dict[str, Any]]) -> None:
    need([r["case"] for r in rows] == list(CASES), "cold expected/executed population")
    for row in rows:
        row["executed_substeps"] = len(row.get("observations", []))
        row["expected_substeps"] = EXPECTED_SUBSTEPS[row["case"]]
        need(not row.get("skipped") and row["executed_substeps"] == row["expected_substeps"], "case substep population")


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
    def __init__(self, root: Path, seconds: float = 1800, reserve: float = 0) -> None:
        self.root, self.deadline = root, time.monotonic() + seconds
        self.work_deadline = self.deadline - reserve
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
                cwd: Path | None = None, env: dict[str, str] | None = None, raw: bool = False) -> tuple[int, str, str]:
        if not cleanup:
            self.check()
        remaining = min(cap, (self.deadline if cleanup else self.work_deadline) - time.monotonic())
        need(remaining > 0, "no launch after expiry")
        self.used = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        need(self.used + 2 * LIMIT <= 63 * LIMIT, "parent streams/diagnostic reserve")
        self.calls += 1
        paths = [self.root / f"command-{self.calls}.{s}" for s in ("out", "err")]
        launcher = "import resource,os,sys;resource.setrlimit(resource.RLIMIT_FSIZE,(int(sys.argv[1]),)*2);os.execvp(sys.argv[2],sys.argv[2:])"
        with paths[0].open("xb") as out, paths[1].open("xb") as err:
            remaining = min(cap, (self.deadline if cleanup else self.work_deadline) - time.monotonic())
            need(remaining > 0, "no launch after expiry")
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
        return p.returncode, "" if raw else paths[0].read_text(), paths[1].read_text()


def stage_context(budget: Budget, context: Path, paths: list[str], repo: Path) -> list[dict[str, Any]]:
    rc, listing, _ = budget.command(["git", "ls-tree", "-rlz", "HEAD", "--", *paths], cwd=repo)
    need(rc == 0 and listing, "selected Git source population")
    entries = []
    for record in listing.rstrip("\0").split("\0"):
        metadata, name = record.split("\t", 1)
        mode, kind, oid, size = metadata.split()
        need(mode in ("100644", "100755") and kind == "blob" and not Path(name).is_absolute()
             and ".." not in Path(name).parts and int(size) < LIMIT, "regular bounded source blob")
        need(budget.command(["git", "cat-file", "blob", oid], cwd=repo, raw=True)[0] == 0, "source blob unavailable")
        data = (budget.root / f"command-{budget.calls}.out").read_bytes()
        need(len(data) == int(size), "source blob length")
        target = context / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if mode == "100755" else 0o644)
        entries.append({"path": name, "mode": mode, "object_id": oid, "bytes": len(data)})
        budget.check()
    return entries


def failure_diagnostic(path: Path, value: dict[str, Any]) -> None:
    value = {**value, "status": "UNKNOWN diagnostic; not completion evidence",
             "publication_scope": "outside completion budget; failure retention only"}
    payload = json.dumps(value, indent=2) + "\n"
    need(len(payload.encode()) <= LIMIT, "failure diagnostic limit")
    path.write_text(payload)


def cleanup_owned(budget: Budget, containers: list[str], tags: list[str], nonce: str) -> list[dict[str, Any]]:
    outcomes = []
    for kind, names in (("container", containers), ("image", tags)):
        for name in reversed(names):
            row: dict[str, Any] = {"kind": kind, "name": name, "absent": False}
            prefix = ["docker"] + (["image"] if kind == "image" else [])
            try:
                rc, out, err = budget.command([*prefix, "inspect", name], cleanup=True)
                if rc:
                    need("No such" in err, "ownership/absence unavailable")
                else:
                    need(json.loads(out)[0]["Config"]["Labels"]["skillc.b3a"] == nonce, "refuse foreign cleanup")
                    remove = [*prefix, "rm"] + (["-f"] if kind == "container" else [])
                    need(budget.command([*remove, name], cleanup=True)[0] == 0, "owned removal failed")
                    rc, _, err = budget.command([*prefix, "inspect", name], cleanup=True)
                    need(rc != 0 and "No such" in err, "absence unconfirmed")
                row["absent"] = True
            except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                row["error"] = str(exc)
            outcomes.append(row)
            try:
                (budget.root / "cleanup.json").write_text(json.dumps(outcomes, indent=2) + "\n")
            except OSError as exc:
                row.update(absent=False, retention_error=str(exc))
    return outcomes


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
    if case == "cold-install-clean":
        rc, versions = call(["bash", "-c", "python --version; uv --version; dpkg-query -W git make bash"], project)
        need(rc == 0 and "Python 3." in versions and "uv 0.9.7" in versions
             and all(name + "\t" in versions for name in ("git", "make", "bash")), "actual runtime tool versions")
    if case == "cold-sibling-route":
        # Committed pre-fix input: exactly the preferred sibling declaration is absent.
        raw = json.loads(decl.read_text())
        dep = next(d for d in raw["dependencies"] if d["id"] == "helper-flow-auto")
        dep["paths"].remove("stash-worktree-guard.sh")
        before = profile.validate(profile.Profile.from_dict(raw, decl.parent), profile.DirTree(source))
        need(len(profile.installed_home_files(before, profile.DirTree(source))) == 120, "pre-fix population")
        old_home = home / "before"
        old_home.mkdir()
        profile.install(before, profile.DirTree(source), old_home)
        observations.append({"pre_fix_installed_files": 120})
        def route_verdict(rc: int, text: str) -> None:
            need(rc == 0 and ("STASH_GUARD=current" in text or "STASH_GUARD=installed" in text), "actual sibling positive")
        rc, text = call(["bash", str(old_home / ".claude/scripts/flow-start-resolve.sh"), "--verify", "42", "issue-42-cold"], project)
        need(rc == 0 and "STASH_GUARD=unknown" in text, "specific pre-fix sibling absence reached")
        try:
            route_verdict(rc, text)
        except RuntimeError as exc:
            need(str(exc) == "actual sibling positive", "unrelated pre-fix cause")
            observations.append({"pre_fix_consumer": "RED: unknown stash guard"})
        else:
            raise RuntimeError("120-file consuming control blind")
        for directory in (preferred, bundled):
            rc, text = call(["bash", str(directory / "flow-start-resolve.sh"), "--verify", "42", "issue-42-cold"], project)
            route_verdict(rc, text)
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
        need(next(r for r in rows if r["destination"] == ".claude/scripts/flow-start-resolve.sh")["status"] == "violated", "mutated path cause")
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
                need((rc == 0) == passing and "test_active" in text and "Ran 1 test" in text,
                     "real check-plan must execute the selected active test")
                need(("OK" in text) if passing else ("FAIL: test_active" in text and "AssertionError" in text),
                     "runner verdict must come from the actual active test")
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
    budget = Budget(tmp, reserve=120)
    nonce = uuid.uuid4().hex
    containers: list[str] = []
    images: list[str] = []
    tags: list[str] = []
    rows: list[dict[str, Any]] = []
    cleanup: list[Any] = []
    identities: dict[str, Any] = {"images": [], "build_dispositions": {}}
    def ownership() -> None:
        (tmp / "owned.json").write_text(json.dumps({"nonce": nonce, "containers": containers,
            "tags": tags, "images": images, "identities": identities}, indent=2) + "\n")
    ownership()
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
        rc, head, _ = budget.command(["git", "rev-parse", "HEAD"])
        need(rc == 0, "source commit unavailable")
        rc, tree_id, _ = budget.command(["git", "rev-parse", "HEAD^{tree}"])
        need(rc == 0, "source tree unavailable")
        identities.update(commit=head.strip(), tree=tree_id.strip())
        identities["source_files"] = stage_context(budget, context, paths, spec.ROOT)
        for entry in identities["source_files"]:
            need((context / entry["path"]).read_bytes() == (spec.ROOT / entry["path"]).read_bytes(), "export source identity")
        for target in ("cached", "uncached"):
            tag = f"skillc-b3a-{nonce}:{target}"
            tags.append(tag)
            ownership()
            identities["build_dispositions"][target] = "active or cancellation unconfirmed"
            ownership()
            rc, _, err = budget.command(["docker", "build", "--target", target, "--label", f"skillc.b3a={nonce}",
                                        "-t", tag, "-f", str(context / "docker/profile-flow-auto-568/Dockerfile"), str(context)], 300)
            need(rc == 0, "purpose image build unavailable: " + err[-500:])
            identities["build_dispositions"][target] = "command completed"
            rc, output, _ = budget.command(["docker", "image", "inspect", tag])
            info = json.loads(output)[0]
            need(rc == 0 and info["Config"]["Labels"]["skillc.b3a"] == nonce, "owned image identity")
            images.append(info["Id"])
            identities["images"].append({"target": target, "tag": tag, "id": info["Id"], "label": nonce})
            ownership()
        spec.check_source()
        identities["source_manifest_sha256"] = hashlib.sha256((json.dumps(spec.source_manifest(), indent=2) + "\n").encode()).hexdigest()
        inv, tree = spec.inventory()
        need(len(spec.profile.installed_home_files(inv, tree)) == 121, "normal source closure")
        rows.append({"case": CASES[0], "observations": [{"source_files": 388, "installed_plan": 121}]})
        raw = json.loads(spec.DECLARATION.read_text())
        raw["dependencies"] = [d for d in raw["dependencies"] if d["id"] != "helper-gate-lib"]
        try:
            spec.profile.validate(spec.profile.Profile.from_dict(raw, spec.DECLARATION.parent), tree)
        except spec.profile.Refused:
            rows.append({"case": CASES[1], "observations": [{"negative": "normal validator REFUSED"}]})
        else:
            raise RuntimeError("missing dependency accepted")
        for case in CASES[2:]:
            case_end = min(budget.deadline, time.monotonic() + 60)
            name = f"skillc-b3a-{nonce}-{len(containers)}"
            containers.append(name)  # Ownership name recorded BEFORE daemon allocation.
            ownership()
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
                rows.append({"case": case, "observations": [{"negative": "actual synthetic bind REFUSED"}]})
                continue
            settings(info)
            rc, output, err = budget.command(["docker", "start", "-a", name], min(60, case_end - time.monotonic()))
            need(rc == 0, "actor unavailable: " + err[-1000:] + output[-1000:])
            row = json.loads(output)
            need(row["case"] == case and time.monotonic() < case_end, "case identity/deadline")
            rows.append(row)
    finally:
        cleanup = cleanup_owned(budget, containers, tags, nonce)
        failure_diagnostic(tmp / "cold-diagnostic.json", {"identities": identities, "containers": containers,
            "tags": tags, "cleanup": cleanup, "commands": budget.events,
            "partial_cases": [{"case": r["case"], "observed_substeps": len(r.get("observations", []))} for r in rows]})
        need(all(r["absent"] for r in cleanup), "cleanup unconfirmed; owned rescue required")
    budget.check()
    case_population(rows)
    report = {"cases": rows, "cleanup": cleanup, "commands": budget.events,
              "identities": identities, "parent_bytes": budget.used, "status": "BOUNDED COLD PROOF; full flow UNPROVEN"}
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

    @pytest.mark.parametrize("fault", ["network", "root", "memory", "swap", "cpu", "pids", "tmpfs", "bind"])
    def test_containment_classifier_has_positive_and_negative(tmp_path: Path, fault: str) -> None:
        info: dict[str, Any] = {"HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True,
            "Memory": 512 * LIMIT, "MemorySwap": 512 * LIMIT, "NanoCpus": 1_000_000_000,
            "PidsLimit": 128, "Tmpfs": {"/home/proof": "rw,size=256m", "/work": "rw,size=256m",
                                      "/project": "rw,size=32m", "/tmp": "rw,size=64m"}}, "Mounts": []}
        settings(info)
        field = {"network": "NetworkMode", "root": "ReadonlyRootfs", "memory": "Memory", "swap": "MemorySwap",
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

    @pytest.mark.parametrize("fault", ["early-error", "expired", "image-still-present"])
    def test_cleanup_accounts_every_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
        budget = Budget(tmp_path)
        seen: list[str] = []
        if fault == "expired":
            budget.deadline = time.monotonic() - 1
        else:
            def command(argv: list[str], **kw: Any) -> tuple[int, str, str]:
                seen.append(argv[-1])
                if fault == "early-error" and argv[-1] == "first":
                    raise OSError("controlled first cleanup failure")
                if fault == "image-still-present":
                    return 0, json.dumps([{"Config": {"Labels": {"skillc.b3a": "owned"}}}]), ""
                return 1, "", "No such container"
            monkeypatch.setattr(budget, "command", command)
        rows = cleanup_owned(budget, ["second", "first"], ["tag"], "owned")
        assert len(rows) == 3
        if fault == "early-error":
            assert not rows[0]["absent"] and rows[1]["absent"] and rows[2]["absent"]
            assert seen == ["first", "second", "tag"]
        else:
            assert not any(r["absent"] for r in rows)
        if fault == "expired":
            assert budget.calls == 0

    def test_expired_cleanup_never_launches(tmp_path: Path) -> None:
        budget = Budget(tmp_path, -1)
        marker = tmp_path / "must-not-launch"
        with pytest.raises(RuntimeError, match="no launch after expiry"):
            budget.command([sys.executable, "-c", f"open({str(marker)!r},'w').write('launched')"], cleanup=True)
        assert not marker.exists() and budget.calls == 0

    @pytest.mark.parametrize("fault", ["empty", "missing", "duplicate", "extra", "skipped", "substep"])
    def test_physical_population_refuses_incomplete_inputs(fault: str) -> None:
        rows: list[dict[str, Any]] = [{"case": case, "observations": [{} for _ in range(EXPECTED_SUBSTEPS[case])]} for case in CASES]
        case_population(rows)
        if fault == "empty":
            rows.clear()
        elif fault == "missing":
            rows.pop()
        elif fault in ("duplicate", "extra"):
            rows.append(rows[-1] if fault == "duplicate" else {"case": "undeclared"})
        elif fault == "skipped":
            rows[0]["skipped"] = True
        else:
            rows[0]["observations"] = []
        with pytest.raises(RuntimeError):
            case_population(rows)

    def test_failure_diagnostic_retains_owned_rescue_fields(tmp_path: Path) -> None:
        value = {"identities": {"build_disposition": "cancellation unconfirmed"},
                 "containers": ["owned"], "tags": ["owned-tag"], "cleanup": [{"absent": False}],
                 "commands": [{"returncode": 1}], "partial_cases": [{"case": CASES[0]}]}
        failure_diagnostic(tmp_path / "unknown.json", value)
        observed = json.loads((tmp_path / "unknown.json").read_text())
        assert all(observed[k] == v for k, v in value.items())
        assert "UNKNOWN" in observed["status"] and "outside completion budget" in observed["publication_scope"]

    def test_cleanup_continues_after_retention_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        budget, seen = Budget(tmp_path), []
        def command(argv: list[str], **kw: Any) -> tuple[int, str, str]:
            seen.append(argv[-1])
            return 1, "", "No such container"
        write = Path.write_text
        failed: list[bool] = []
        def unavailable(path: Path, data: str, **kw: Any) -> int:
            if path.name == "cleanup.json" and not failed:
                failed.append(True)
                raise OSError("controlled diagnostic retention failure")
            return write(path, data, **kw)
        monkeypatch.setattr(budget, "command", command)
        monkeypatch.setattr(Path, "write_text", unavailable)
        rows = cleanup_owned(budget, ["second", "first"], ["tag"], "owned")
        assert seen == ["first", "second", "tag"] and failed
        assert not rows[0]["absent"] and rows[1]["absent"] and rows[2]["absent"]
        assert "retention_error" in rows[0]

    def test_staging_large_aggregate_preserves_blob_bytes_and_modes(tmp_path: Path) -> None:
        repo, context = tmp_path / "repo", tmp_path / "context"
        repo.mkdir()
        budget = Budget(tmp_path)
        for args in (["init", "-q"], ["config", "user.name", "fixture"], ["config", "user.email", "fixture@example.invalid"]):
            assert budget.command(["git", *args], cwd=repo)[0] == 0
        data = (b"line\r\n" + bytes(range(256))) * 1100
        for name in ("a", "b", "c", "d", "e"):
            (repo / name).write_bytes(data)
        (repo / "a").chmod(0o755)
        for args in (["add", "."], ["-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-qm", "seed"]):
            assert budget.command(["git", *args], cwd=repo)[0] == 0
        rc, _, err = budget.command(["git", "archive", "--output", str(tmp_path / "old.tar"), "HEAD"], cwd=repo)
        assert rc != 0 and "File too large" in err  # Actual old path's other verdict.
        start = budget.calls
        entries = stage_context(budget, context, ["."], repo)
        assert len(entries) == 5 and budget.calls - start == 6
        assert sum(r["bytes"] for r in entries) > LIMIT
        assert all((context / r["path"]).read_bytes() == data for r in entries)
        assert (context / "a").stat().st_mode & 0o111
        with pytest.raises(RuntimeError, match="selected Git source population"):
            stage_context(budget, context, ["absent-selection"], repo)
        (repo / "oversized").write_bytes(b"x" * LIMIT)
        for args in (["add", "oversized"], ["-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-qm", "oversized control"]):
            assert budget.command(["git", *args], cwd=repo)[0] == 0
        with pytest.raises(RuntimeError, match="regular bounded source blob"):
            stage_context(budget, context, ["oversized"], repo)
