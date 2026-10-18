"""Real Docker acceptance of the local CI/CD capability profile (skillc#280).

The `cpp-codex-cicd-86641e8` closure is installed into a cold `--network none`
container built from the cicd runtime: the validated flow-check profile-runtime
image plus one curl layer (docker/cicd-trial/). The runtime is the one the
closure itself SELECTS (`runtime_supply.selected_runtime`), validated through
the production `DockerBackend.runtime_environment` and `_preflight_in_container`.
Nothing is mounted. The installed home and the project enter by copy only.

Every CPP command runs as the installed skill documents it. The test reads
the `Locate CPP Source` block and each command line out of the INSTALLED
reference/SKILL bytes and fails if CPP's text no longer carries them, so a
pass is about CPP's real integration, not a paraphrase of it. Against
tests/fixtures/cicd-local/project (stdlib-only, CPP's real cicd.yml schema)
and its loopback health service, the run must show:

- `detect` names Python/uv; `check` reports 8/8 targets;
- `run --plan check` (the runner flow-check's own gate drives) runs lint,
  test and typecheck to success, offline, and `make build` produces an
  artifact holding the package source (the runner's github.com probe fails
  at name resolution under `--network none`; CPP_OFFLINE is not set);
- with the service DOWN, `health` fails its one endpoint;
- with it UP, `health` and `smoke` pass, `verify --baseline` then `verify`
  says PROCEED;
- the service stopped again, `verify` says ROLLBACK (exit 1);
- `templates/cicd.yml.example`'s shape (claude-power-pack#1476) configures
  ZERO probes: `health` says "no checks configured" (exit 0 in its default
  mode) and `verify` says REVIEW;
- `pipeline --write` emits GitHub Actions and Woodpecker YAML whose make
  targets are exactly the ones the local plan ran. The provider files are
  parsed, never executed: their `pip install uv` / `uv sync` steps and
  container images are provider-only semantics;
- cleanup: the service process is gone before teardown and the container is
  gone after it. Images are removed only under run-real-docker's run.lock
  (SKILLC_REAL_DOCKER_RUN_LOCK_HELD=1), and then only ones absent before the
  build; an unlocked run keeps its tagged build and removes nothing. Nothing
  is ever pruned.

BREAK MODES (`SKILLC_CICD_PROFILE_LIVE_BREAK`, ci/real-docker/break-lib.sh's
`cicdprofile:` family). Each plants exactly one input and is strict-xfail on
its own property exception, so an unrelated failure is never credited and a
missed break is XPASS:

    none          the full run above.
    no-curl       curl removed from the container (as root) after runtime
                  validation, before preflight -> tool-curl refused.
    old-curl      curl replaced by a stub reporting 6.1.0 -> tool-curl's
                  `>=7.0` constraint refused.
    service-down  the health service is never started -> the healthy-deploy
                  property (all health checks pass, verify PROCEEDs) fails.
    no-probes     the project ships the template-shaped cicd.yml -> the
                  configured-probes property (>=1 health check) fails.
    broken-build  the project's build recipe is `false` -> the build-artifact
                  property (`make build` produces dist/calc.tar holding the
                  package source) fails.

SKIPPED, NOT FAILED, without a reachable Docker daemon; real-daemon runs are
the #315 runner's (ci/check_real_docker_ran.py floor).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT

from skillc import agent_trial as at
from skillc import docker_backend as d
from skillc import materialize as m
from skillc import profile as p
from skillc import runtime_supply as rs
from skillc.backend import Confirmation, ExecuteResult, Limits

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "profile-cpp-codex-cicd-86641e8"
PROFILE_JSON = ROOT / "evals" / "subjects" / "cpp-codex-cicd-86641e8" / "profile.json"
PROJECT = ROOT / "tests" / "fixtures" / "cicd-local" / "project"
TEMPLATE_SHAPE = ROOT / "tests" / "fixtures" / "cicd-local" / "template-shape.cicd.yml"

BREAK_MODE = os.environ.get("SKILLC_CICD_PROFILE_LIVE_BREAK", "none")
_VALID_BREAK_MODES = ("none", "no-curl", "old-curl", "service-down", "no-probes", "broken-build")
if BREAK_MODE not in _VALID_BREAK_MODES:
    raise RuntimeError(f"SKILLC_CICD_PROFILE_LIVE_BREAK={BREAK_MODE!r} must be one of {_VALID_BREAK_MODES}")

_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or d.probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - real-daemon execution is owed to the real-Docker runner (#315)",
    ),
]

_LIMITS = Limits(timeout=180.0, max_captured_stdout_bytes=1_000_000)
_PROJECT_DIR = f"{d.CONTAINER_WORKSPACE}/project"
_SERVICE_URL = "http://127.0.0.1:18080/health"
_BUILD_RECIPE = b"build:\n\tmkdir -p dist && tar -cf dist/calc.tar src\n"
_FAKE_OLD_CURL = b"#!/bin/sh\necho 'curl 6.1.0 (skillc#280 old-curl stub)'\n"

#: (installed skill file, the exact command line it documents).
_LINES = {
    "detect": ("cicd-init/reference.md",
               'PYTHONPATH="$CPP_DIR:$PYTHONPATH" uv run --project "$CPP_DIR" python -m lib.cicd detect'),
    "check": ("cicd-check/reference.md",
              'PYTHONPATH="$CPP_DIR:$PYTHONPATH" uv run --project "$CPP_DIR" python -m lib.cicd check'),
    "health": ("cicd-health/reference.md",
               'PYTHONPATH="$CPP_DIR:$PYTHONPATH" uv run --project "$CPP_DIR" python -m lib.cicd health'),
    "smoke": ("cicd-smoke/reference.md",
              'PYTHONPATH="$CPP_DIR:$PYTHONPATH" uv run --project "$CPP_DIR" python -m lib.cicd smoke'),
    "baseline": ("cicd-verify/reference.md",
                 'PYTHONPATH="$CPP_DIR:$PYTHONPATH" uv run --project "$CPP_DIR" python -m lib.cicd verify --baseline'),
    "verify": ("cicd-verify/reference.md",
               'PYTHONPATH="$CPP_DIR:$PYTHONPATH" uv run --project "$CPP_DIR" python -m lib.cicd verify'),
    "pipeline": ("cicd-pipeline/SKILL.md",
                 ('PYTHONPATH="$PWD:$HOME/Projects/claude-power-pack:$PYTHONPATH" uv run --project '
                  '"$HOME/Projects/claude-power-pack" python -m lib.cicd pipeline --write')),
}


class _PropertyHeld(Exception):
    """Base for the per-property exceptions; never raised directly."""


class _CurlToolPropertyHeld(_PropertyHeld):
    """Preflight accepted the declared curl tool."""


class _ProbesConfiguredPropertyHeld(_PropertyHeld):
    """The project's cicd.yml configures at least one health check."""


class _HealthyDeployVerifiesPropertyHeld(_PropertyHeld):
    """Every health check passes and verify against the baseline PROCEEDs."""


class _BuildArtifactPropertyHeld(_PropertyHeld):
    """`make build` succeeds and its artifact carries the package source."""


_MODE_PROPERTY: dict[str, type[_PropertyHeld]] = {
    "no-curl": _CurlToolPropertyHeld,
    "old-curl": _CurlToolPropertyHeld,
    "service-down": _HealthyDeployVerifiesPropertyHeld,
    "no-probes": _ProbesConfiguredPropertyHeld,
    "broken-build": _BuildArtifactPropertyHeld,
}
_CURL_SYMPTOMS = {"no-curl": "not found", "old-curl": "6.1.0"}


def _require(cls: type[_PropertyHeld], condition: bool, message: str) -> None:
    if not condition:
        raise cls(message)


def _load_builder(name: str, relpath: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _closure() -> tuple[dict[str, bytes], dict[str, str], tuple[dict[str, Any], ...]]:
    """HOST PHASE from the committed pin snapshot; the closure must select the
    cicd runtime through the production selector, never by this test's say-so."""
    prof = p.Profile.load(PROFILE_JSON)
    tree = p.DirTree(FIXTURE_DIR)
    inventory = p.validate(prof, tree)
    home_files = p.installed_home_files(inventory, tree)
    verify_home_files = {relpath: m.sha256_bytes(data) for relpath, data in home_files.items()}
    tools = tuple(dep for dep in inventory["dependencies"] if dep["kind"] == "tool")
    # A snapshot tree reports a `snapshot:` revision; production selects on the
    # acquired subject's pin (cli.py), which is the declared one here.
    subject = json.loads((PROFILE_JSON.parent / "subject.json").read_text(encoding="utf-8"))
    selected = rs.selected_runtime(
        locator=subject["locator"], revision=subject["revision"],
        gate_entrypoint=inventory["gate_entrypoint"], files=verify_home_files, tools=tools,
    )
    assert selected == rs.CICD_RUNTIME, f"the cicd closure selected {selected!r}"
    return home_files, verify_home_files, tools


def _installed_text(home_files: Mapping[str, bytes], skill_file: str) -> str:
    return home_files[f".codex/skills/{skill_file}"].decode("utf-8")


def _locate_block(home_files: Mapping[str, bytes]) -> str:
    text = _installed_text(home_files, "cicd-health/reference.md")
    found = re.search(r"```bash\n(CPP_DIR=\"\"\n.*?)```", text, re.DOTALL)
    assert found is not None, "the installed cicd-health skill no longer documents its CPP_DIR probe"
    return found.group(1)


def _skill_line(home_files: Mapping[str, bytes], key: str) -> str:
    skill_file, line = _LINES[key]
    assert line in _installed_text(home_files, skill_file).splitlines(), (
        f"the installed {skill_file} no longer documents {key!r} this way"
    )
    return line


def _sh(backend: d.DockerBackend, handle: object, script: str) -> tuple[int | None, str]:
    result: ExecuteResult = backend.exec_in_attempt(handle, ["bash", "-c", script], _LIMITS)
    assert result.reason == "exited" and result.stdout is not None and not result.stdout_truncated, (
        f"container command did not complete (reason={result.reason!r})"
    )
    return result.exit_code, result.stdout.decode("utf-8", errors="replace")


def _as_root(handle: object, argv: list[str], stdin: bytes | None = None) -> None:
    name = handle.name  # type: ignore[attr-defined]
    done = subprocess.run(["docker", "exec", "-i", "-u", "0", name, *argv], input=stdin,
                          capture_output=True, check=False, timeout=60)
    assert done.returncode == 0, f"root fault plant failed: {done.stderr!r}"


def _plant_curl_fault(handle: object, mode: str) -> None:
    if mode == "no-curl":
        _as_root(handle, ["rm", "-f", "/usr/bin/curl"])
    elif mode == "old-curl":
        _as_root(handle, ["sh", "-c", "cat > /usr/bin/curl && chmod 755 /usr/bin/curl"], _FAKE_OLD_CURL)


def _check_curl_preflight(refused: bool, reason: str) -> None:
    """The refusal's identity is checked first; the healthy predicate never
    depends on the mode."""
    if refused:
        assert BREAK_MODE in _CURL_SYMPTOMS, f"intact closure was unexpectedly refused: {reason}"
        assert reason.startswith("tool dependency 'tool-curl' ") and _CURL_SYMPTOMS[BREAK_MODE] in reason, (
            f"preflight refused for another reason: {reason}"
        )
    _require(_CurlToolPropertyHeld, not refused, "preflight did not accept the declared curl")


def _verdict(text: str) -> str | None:
    found = re.search(r"^Verdict: (PROCEED|REVIEW|ROLLBACK)\b", text, re.MULTILINE)
    return found.group(1) if found else None


_MAKE_COMMAND = re.compile(r"make ([A-Za-z0-9_-]+)")


def _make_targets(pipeline_yaml: Mapping[str, Any]) -> dict[str, set[str]]:
    """Per provider, the make targets its generated steps run.

    Bounded grammar: a command that mentions make must be exactly
    `make <one target>`. Anything else (`make lint deploy`, flags, chains) is
    refused rather than read as its first target, which would hide the rest.
    """
    out: dict[str, set[str]] = {}
    for provider, doc in pipeline_yaml.items():
        commands: list[str] = []
        if provider == "github":
            for job in doc["jobs"].values():
                commands += [step["run"] for step in job["steps"] if "run" in step]
        else:
            for step in doc["steps"]:
                commands += step.get("commands", [])
        targets: set[str] = set()
        for command in commands:
            for line in command.splitlines():
                if re.search(r"\bmake\b", line):
                    found = _MAKE_COMMAND.fullmatch(line.strip())
                    assert found is not None, f"unsupported make command in {provider}: {line.strip()!r}"
                    targets.add(found.group(1))
        out[provider] = targets
    return out


def _host_image_ids() -> set[str]:
    """Every image ID on the daemon, intermediates included."""
    listed = subprocess.run(["docker", "image", "ls", "-a", "-q", "--no-trunc"], capture_output=True,
                            text=True, check=False, timeout=60)
    assert listed.returncode == 0, f"cannot list host images: {listed.stderr}"
    return set(listed.stdout.split())


#: run-real-docker holds evals26's run.lock for the whole pytest run and says
#: so (#414). Only then is "absent from my snapshot" the same as "mine": a
#: co-tenant building during an unlocked run makes images this run never made.
_RUN_LOCK_HELD = os.environ.get("SKILLC_REAL_DOCKER_RUN_LOCK_HELD") == "1"


def _images_to_remove(preexisting: set[str], built: list[str]) -> list[str]:
    """The images this run may remove: only ones it CREATED, layered first.

    The host is shared (#414's lesson): a cached build returns the ID of an
    image that may already exist - the runner's own runtime image, another
    session's - and that one, with every tag on it, must survive this test.
    """
    return [image for image in dict.fromkeys(built) if image not in preexisting]


def _release_images(preexisting: set[str], built: list[str], *, lock_held: bool,
                    remove: Callable[[str], object]) -> list[str]:
    """Remove this run's images only under the runner's exclusive lock.

    Unlocked (a developer host, another session's suite), the build is KEPT:
    both images carry a builder tag, so no prune takes them as dangling, and
    nothing at all is removed.
    """
    if not lock_held:
        return []
    released = _images_to_remove(preexisting, built)
    for image in released:
        remove(image)
    return released


_YAML_DUMP = (
    "import json, yaml; print(json.dumps({'github': yaml.safe_load(open('.github/workflows/ci.yml')), "
    "'woodpecker': yaml.safe_load(open('.woodpecker.yml'))}))"
)


@pytest.mark.timeout(1800)
@pytest.mark.xfail(
    condition=BREAK_MODE != "none", strict=True, raises=_MODE_PROPERTY.get(BREAK_MODE, _PropertyHeld),
    reason=f"SKILLC_CICD_PROFILE_LIVE_BREAK={BREAK_MODE} deliberately breaks one property",
)
def test_the_cicd_profile_runs_cpps_local_ci_cd_in_a_cold_container() -> None:
    home_files, verify_home_files, tools = _closure()
    locate = _locate_block(home_files)
    lines = {key: _skill_line(home_files, key) for key in _LINES}

    profile_builder = _load_builder("profile_runtime_builder_live_280", "docker/profile-trial/build.py")
    cicd_builder = _load_builder("cicd_runtime_builder_live_280", "docker/cicd-trial/build.py")
    scratch = Path(tempfile.mkdtemp(prefix="sk-280-live-"))
    preexisting = _host_image_ids()
    base_receipt, cicd_receipt = scratch / "base.json", scratch / "cicd.json"
    profile_builder.build_image(ROOT, base_receipt)
    cicd_builder.build_image(base_receipt, cicd_receipt)
    supply = rs.RuntimeSupply.from_path(cicd_receipt)
    rs.require_kind(supply, rs.CICD_RUNTIME)

    surface: dict[str, object] = {
        f"project/{f.relative_to(PROJECT).as_posix()}": f for f in PROJECT.rglob("*") if f.is_file()
    }
    if BREAK_MODE == "no-probes":
        surface["project/.claude/cicd.yml"] = TEMPLATE_SHAPE.read_bytes()
    if BREAK_MODE == "broken-build":
        makefile = (PROJECT / "Makefile").read_bytes()
        assert makefile.count(_BUILD_RECIPE) == 1, "the fixture's build recipe moved; update this break mode"
        surface["project/Makefile"] = makefile.replace(_BUILD_RECIPE, b"build:\n\tfalse\n")

    backend = d.DockerBackend(image=supply.image_id, base_dir=scratch, network="none", runtime_supply=supply,
                              witness_io=True,
                              daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT)
    handle = backend.prepare("a-280-cicd-" + uuid.uuid4().hex)
    try:
        backend.install(handle, surface)
        for relpath, data in home_files.items():
            backend.deliver_home_file(handle, relpath, data)
        assert backend.image_id(handle) == supply.image_id
        backend.runtime_environment(handle, _LIMITS, verify_home_files)
        _plant_curl_fault(handle, BREAK_MODE)

        refused, reason = False, ""
        try:
            at._preflight_in_container(backend, handle, _LIMITS, verify_home_files, tools)
        except at.HomeFileVerificationRefused as exc:
            refused, reason = True, str(exc)
        _check_curl_preflight(refused, reason)

        def cicd(key: str) -> tuple[int | None, str]:
            return _sh(backend, handle, f"cd {_PROJECT_DIR}\n{locate}\n{lines[key]}")

        code, out = cicd("detect")
        assert code == 0 and re.search(r"^Framework:\s+Python$", out, re.MULTILINE) and re.search(
            r"^Package Manager: uv$", out, re.MULTILINE), "detect did not name Python/uv"
        code, out = cicd("check")
        assert code == 0 and "Makefile OK (8/8 targets)" in out, "check did not pass the project's Makefile"
        # flow-check's runner invocation, in the same documented shape.
        code, out = _sh(backend, handle, f"cd {_PROJECT_DIR}\n{locate}\n" + lines["check"].replace(
            "lib.cicd check", "lib.cicd run --plan check --no-json") + " 2>&1")  # progress is on stderr
        plan_steps = re.findall(r"^\s+\[\d/\d\] (\w+): SUCCESS", out, re.MULTILINE)
        assert code == 0 and "Plan 'check' completed successfully (3/3 steps)" in out, "the local plan failed"
        assert plan_steps == ["lint", "test", "typecheck"], plan_steps
        code, out = _sh(backend, handle, f"cd {_PROJECT_DIR}\nmake build >/dev/null 2>&1 || exit 1\ntar -tf dist/calc.tar")
        _require(_BuildArtifactPropertyHeld, code == 0 and "src/calc/__init__.py" in out.split(),
                 f"make build did not produce the package artifact (exit {code})")

        code, out = _sh(backend, handle, f"cd {_PROJECT_DIR}\n{locate}\n{lines['health']} --json")
        configured = json.loads(out)
        _require(_ProbesConfiguredPropertyHeld, configured["total"] >= 1, "cicd.yml configures no health check")
        assert code == 1 and configured["failed"] == 1, "a DOWN service must fail its one endpoint"

        pid = ""
        if BREAK_MODE != "service-down":
            code, out = _sh(backend, handle, (
                f"cd {_PROJECT_DIR}\nnohup python3 src/calc/service.py </dev/null >/tmp/calc-service.log 2>&1 &\n"
                "echo $!\npython3 -c \"import time,urllib.request\nfor _ in range(100):\n"
                f"    try: urllib.request.urlopen('{_SERVICE_URL}', timeout=1); break\n"
                "    except OSError: time.sleep(0.1)\nelse: raise SystemExit('service never answered')\""))
            assert code == 0, f"the loopback service did not start: {out}"
            pid = out.split()[0]

        health_code, health = cicd("health")
        code, out = cicd("baseline")
        assert code == 0 and "Saved baseline" in out, "verify --baseline did not capture"
        verify_code, verify = cicd("verify")
        _require(_HealthyDeployVerifiesPropertyHeld,
                 health_code == 0 and "Health: 1/1 checks passed" in health
                 and verify_code == 0 and _verdict(verify) == "PROCEED",
                 f"a healthy deploy did not verify (health exit {health_code}, verdict {_verdict(verify)})")

        code, out = cicd("smoke")
        assert code == 0 and "Smoke: 2/2 tests passed" in out, "smoke tests failed against the live service"

        code, out = cicd("pipeline")
        assert code == 0 and "Wrote: .github/workflows/ci.yml" in out and "Wrote: .woodpecker.yml" in out
        code, out = _sh(backend, handle, f'cd {_PROJECT_DIR}\nuv run -q --project "$HOME/Projects/claude-power-pack" '
                                         f'python -c "{_YAML_DUMP}"')
        assert code == 0, f"generated provider YAML did not parse: {out}"
        assert _make_targets(json.loads(out)) == {"github": set(plan_steps), "woodpecker": set(plan_steps)}

        # Unreachable service after a healthy baseline: an explicit ROLLBACK.
        code, out = _sh(backend, handle, f"kill {pid}\nfor _ in $(seq 50); do [ -e /proc/{pid} ] || exit 0; "
                                         "sleep 0.1; done; exit 1")
        assert code == 0, "the service process outlived its stop"
        code, out = cicd("verify")
        assert code == 1 and _verdict(out) == "ROLLBACK", "an unreachable service did not roll back"

        # templates/cicd.yml.example's shape: zero probes, reported, never a pass.
        _sh(backend, handle, f"rm -f {_PROJECT_DIR}/.claude/deploy-baseline.json")
        swapped = backend.exec_in_attempt(handle, ["bash", "-c", f"cat > {_PROJECT_DIR}/.claude/cicd.yml"],
                                          _LIMITS, stdin=TEMPLATE_SHAPE.read_bytes())
        assert swapped.reason == "exited" and swapped.exit_code == 0, "could not swap in the template shape"
        code, out = cicd("health")
        assert code == 0 and "Health Check: no checks configured" in out, "template shape was not reported empty"
        code, out = cicd("verify")
        assert _verdict(out) == "REVIEW" and "No health or smoke probes configured" in out, (
            "zero probes did not verify as REVIEW")
    finally:
        backend.destroy(handle)
        # A genuine "no such object" from the daemon, never any nonzero inspect
        # (an unreachable daemon is UNKNOWN). Checked here, so a break mode's
        # property exception cannot hide a container that survived teardown.
        absent = backend.confirm_absent(handle)
        # Only images this run created, the layered one first (a base cannot be
        # removed while a child exists). A pre-existing base keeps the builder's
        # `skillc-cicd-base:` tag: removing a tag can delete an untagged image.
        # Never a prune.
        built = [supply.image_id, json.loads(base_receipt.read_bytes())["image_id"]]
        _release_images(preexisting, built, lock_held=_RUN_LOCK_HELD, remove=lambda image: subprocess.run(
            ["docker", "image", "rm", "-f", image], capture_output=True, check=False))
        shutil.rmtree(scratch, ignore_errors=True)
        assert absent is Confirmation.CONFIRMED, f"the attempt container's removal is {absent.name}"
