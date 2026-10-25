"""Certify the fixed trusted artifact population; no arbitrary candidate option."""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
_spec = importlib.util.spec_from_file_location("inventory568_oracle", Path(__file__).with_name("oracle.py"))
o = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(o)

CASES = ["reference-valid-pack", "alternative-valid-pack", "initial-missing-batch", "csv-only-importer", "partial-commit-late-invalid", "shared-replace-regression", "duplicate-first-wins", "boolean-as-integer", "metadata-overwrite", "false-completion", "benign-refactor", "remote-correct-local-wrong", "remote-wrong-local-correct", "unreadable-remote-object", "unsupported-packed-remote", "missing-selected-python", "simulated-required-import-unavailable", "missing-or-empty-own-case-population", "all-skipped-test-probe", "always-pass-grader", "always-fail-grader", "crash-grader", "no-output-grader", "timed-out-probe-with-child"]
VECTORS = ["legacy-set-existing", "legacy-list-order", "legacy-new-defaults", "csv-valid-update-insert-and-duplicates", "csv-reversed-header", "csv-header-only", "csv-empty", "csv-duplicate-header", "csv-extra-column", "csv-bad-sku", "csv-bad-quantity", "csv-late-invalid-rollback", "jsonl-valid-update-insert-and-duplicates", "jsonl-empty", "jsonl-missing-extra-key", "jsonl-duplicate-key", "jsonl-boolean", "jsonl-float", "jsonl-null", "jsonl-late-invalid-rollback", "input-bad-utf8", "input-missing", "db-missing", "db-uninitialized"]
PROTECTION = ["reference", "alternative", "csv-only", "jsonl-only", "partial", "replace"]
RESOURCES = ["stdout-overflow", "stderr-overflow", "staging-overflow", "owned-child-timeout"]


class Refused(Exception):
    pass


def need(value, message):
    if not value:
        raise Refused(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate manifest key")
        result[key] = value
    return result


def manifest(sources):
    m = json.loads(sources["controls.json"], object_pairs_hook=unique)
    need(m.get("version") == 1 and type(m["version"]) is int, "manifest version")
    need(m.get("cases") == CASES, "case population differs, empty, or duplicated")
    need([v.get("id") for v in m.get("vectors", [])] == VECTORS, "vector population differs")
    need(m.get("protection") == PROTECTION, "protection population differs")
    need(m.get("resource_probes") == RESOURCES, "resource population differs")
    need(set(m.get("mutations", {})) == {"csv-only", "jsonl-only", "partial", "replace", "first-wins", "boolean", "metadata"},
         "mutation population differs")
    return m


def verdict(result):
    return "PASS" if result["feature"] and result["legacy"] else "FAIL"


def reconcile(actual):
    need(actual == {"good": "PASS", "bad": "FAIL", "missing": "UNKNOWN"}, "grader failed distinguishing inputs")


def grader_control(name, budget):
    programs = {
        "always-pass-grader": "import json;print(json.dumps(dict.fromkeys(['good','bad','missing'],'PASS')))",
        "always-fail-grader": "import json;print(json.dumps(dict.fromkeys(['good','bad','missing'],'FAIL')))",
        "crash-grader": "raise RuntimeError('controlled unavailable grader')",
        "no-output-grader": "pass"}
    rc, out, _ = o.bounded([sys.executable, "-c", programs[name]], o.ROOT, budget)
    try:
        need(rc == 0, "grader crashed")
        reconcile(json.loads(out))
    except (Refused, ValueError):
        return "REFUSED"
    return "PASS"


def stopped(pid):
    if not Path("/proc/self/stat").is_file():
        raise o.Unavailable("Linux proc status required for child control")
    try:
        text = Path("/proc") / str(pid) / "stat"
        return text.read_text().rsplit(")", 1)[1].split()[0] in ("Z", "X")
    except FileNotFoundError:
        return True


def child_probe(budget, slow=True):
    with tempfile.TemporaryDirectory(prefix="568-child-") as tmp:
        d = Path(tmp)
        script = ("import subprocess,sys,json,time,os;"
                  "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
                  "open('child.json','w').write(json.dumps({'pid':p.pid,'alive':p.poll() is None}));"
                  + ("time.sleep(60)" if slow else "p.terminate();p.wait(timeout=1)"))
        timed_out = False
        try:
            o.bounded([sys.executable, "-c", script], d, budget, seconds=0.3 if slow else 5)
        except o.Unavailable as exc:
            need("timeout" in str(exc), "child probe failed before timeout: " + str(exc))
            timed_out = True
        data = json.loads((d / "child.json").read_text())
        need(data["alive"] is True, "controlled child was not live before deadline")
        need(stopped(data["pid"]), "owned child still executing after cleanup")
        need(timed_out == slow, "timeout twin verdict")
        return {"status": "UNKNOWN" if timed_out else "PASS",
                "parent": "reaped", "child": "stopped (may await system zombie reaping)"}


def resources(budget):
    observations = {}
    for fd, name in ((1, "stdout-overflow"), (2, "stderr-overflow")):
        # A second write actually crosses RLIMIT_FSIZE; a short first write alone is insufficient.
        code = f"import os;os.write({fd},b'x'*{o.LIMIT});os.write({fd},b'x')"
        with tempfile.TemporaryDirectory() as d:
            o.bounded([sys.executable, "-c", f"import os;os.write({fd},b'x'*{o.LIMIT - 1})"], d, budget)
            try:
                o.bounded([sys.executable, "-c", code], d, budget)
            except o.Unavailable as exc:
                need("output limit" in str(exc), name + " did not hit output bound")
            else:
                raise Refused(name + " accepted")
        observations[name] = "REFUSED with below-limit twin"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "staged"
        small = o.Budget()
        need(small.capacity == 64 * o.LIMIT, "default staging capacity drift")
        # Construct the quota state; do not claim a physical 64MiB disk-fill test.
        small.used = small.capacity - 1
        small.write(p, b"x")
        need(p.read_bytes() == b"x", "staging positive control")
        try:
            small.write(Path(d) / "overflow", b"y")
        except o.Unavailable:
            need(not (Path(d) / "overflow").exists(), "over-budget write occurred")
        else:
            raise Refused("staging bound blind")
    observations["staging-overflow"] = "REFUSED; constructed default-capacity counter, actual one-byte twin/write"
    positive = child_probe(budget, False)
    negative = child_probe(budget)
    observations["owned-child-timeout"] = {"below": positive, "over": negative}
    return observations


def remote_case(name, m, sources, budget):
    with tempfile.TemporaryDirectory(prefix="568-remote-") as tmp:
        d = Path(tmp)
        seed, export = d / "seed", d / "export"
        remote = export / ".remote/widget.git"
        remote.parent.mkdir(parents=True)
        seed.mkdir()
        good = name != "remote-wrong-local-correct"
        remote_name, local_name = ("reference", "fixture") if good else ("fixture", "reference")
        budget.write(seed / "inventory.py", o.program(remote_name, m, sources))

        def git(*args):
            rc, _, err = o.bounded(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                                     "-c", "gc.auto=0", "-c", "user.name=fixture",
                                     "-c", "user.email=fixture@example.invalid", *args], d, budget)
            if rc:
                raise o.Unavailable("trusted Git fixture failed: " + err)

        git("init", "-q", "--initial-branch=main", str(seed))
        git("-C", str(seed), "add", "inventory.py")
        git("-C", str(seed), "commit", "-qm", "known artifact")
        git("clone", "-q", "--bare", str(seed), str(remote))
        budget.write(export / "repo/inventory.py", o.program(local_name, m, sources))
        held = o.remote_files(export)
        if name == "unreadable-remote-object":
            blob = held["files"]["inventory.py"]["blob"]
            target = remote / "objects" / blob[:2] / blob[2:]
            need(target.is_file(), "unreadable object control not loose")
            target.unlink()
            budget.write(target, b"broken zlib")
            need(target.read_bytes() == b"broken zlib", "corruption precondition failed")
        elif name == "unsupported-packed-remote":
            git("-C", str(remote), "repack", "-ad")
            need(any((remote / "objects/pack").glob("*.pack")), "pack control not installed")
        try:
            captured = o.remote_files(export)
        except o.Unavailable as exc:
            need(name in ("unreadable-remote-object", "unsupported-packed-remote"), "unexpected remote unavailable")
            return {"status": "UNKNOWN", "reason": str(exc), "fixture_precondition": {
                "commit": held["commit"], "tree": held["tree"], "files": o.identity(held["files"])}}
        need(name not in ("unreadable-remote-object", "unsupported-packed-remote"), "bad remote accepted")
        row = m["vectors"][3]
        actual = o.vector(captured["files"]["inventory.py"]["data"], row, budget)
        local = o.vector((export / "repo/inventory.py").read_bytes(), row, budget)
        need(verdict(local) != verdict(actual), "local/remote distinction not exercised")
        return {"status": verdict(actual), "commit": captured["commit"], "tree": captured["tree"],
                "files": o.identity(captured["files"]), "remote_vector": actual, "local_vector": local}


def qualify():
    sources = o.load_sources()
    m = manifest(sources)
    budget = o.Budget()
    results, details, remotes = {}, {}, {}
    programs = dict(zip(CASES[:11], ["reference", "alternative", "fixture", "csv-only", "partial",
                                   "replace", "first-wins", "boolean", "metadata", "fixture", "benign"]))
    expected = ["PASS", "PASS", *["FAIL"] * 8, "PASS", "PASS", "FAIL",
                *["UNKNOWN"] * 4, "REFUSED", "UNKNOWN", *["REFUSED"] * 4, "UNKNOWN"]
    need(len(expected) == 24, "internal expected population")
    for index, name in enumerate(CASES):
        if name in programs:
            observed = o.semantic(programs[name], m, sources, budget)
            need([r["id"] for r in observed["vectors"]] == VECTORS, "executed vectors clipped")
            details[name] = observed
            results[name] = verdict(observed)
            if name == "initial-missing-batch":
                need(observed["legacy"], "initial legacy path not correct")
            if name == "shared-replace-regression":
                need(not observed["legacy"], "REPLACE did not regress legacy behavior")
        elif name in CASES[11:15]:
            remotes[name] = remote_case(name, m, sources, budget)
            results[name] = remotes[name]["status"]
        elif name == "missing-selected-python":
            with tempfile.TemporaryDirectory() as d:
                absent = Path(d) / "no-python"
                need(not absent.exists(), "missing executable precondition")
                try:
                    o.bounded([str(absent)], d, budget)
                except o.Unavailable:
                    results[name] = "UNKNOWN"
        elif name == "simulated-required-import-unavailable":
            rc, _, err = o.bounded([sys.executable, "-c", "import simulated_missing_sqlite_568"], o.ROOT, budget)
            need(rc != 0 and "ModuleNotFoundError" in err, "import-unavailable fault not installed")
            results[name] = "UNKNOWN"
        elif name == "missing-or-empty-own-case-population":
            bad = dict(sources)
            bad["controls.json"] = json.dumps({**m, "cases": []}).encode()
            try:
                manifest(bad)
            except Refused:
                results[name] = "REFUSED"
        elif name == "all-skipped-test-probe":
            code = ("import unittest,json;"
                    "T=type('Skipped',(unittest.TestCase,),"
                    "{'test_'+str(i):unittest.skip('controlled')(lambda self:None) for i in range(5)});"
                    "r=unittest.TestResult();unittest.defaultTestLoader.loadTestsFromTestCase(T).run(r);"
                    "print(json.dumps({'count':r.testsRun,'skipped':len(r.skipped),'ok':r.wasSuccessful()}))")
            rc, out, _ = o.bounded([sys.executable, "-c", code], o.ROOT, budget)
            skipped = json.loads(out)
            need(rc == 0 and skipped["count"] == 5 and skipped["skipped"] == 5,
                 "all-skipped precondition did not execute")
            try:
                test_population(skipped)
            except o.Unavailable:
                results[name] = "UNKNOWN"
        elif name.endswith("-grader"):
            results[name] = grader_control(name, budget)
        else:
            results[name] = child_probe(budget)["status"]
        need(results.get(name) == expected[index], name + ": unexpected verdict " + str(results.get(name)))
    protection = []
    for name in PROTECTION:
        row = o.project_tests(name, m, sources, budget)
        test_population(row)
        need(row["ok"] == (name in ("reference", "alternative")), "public test protection: " + name)
        protection.append(row)
    controls = resources(budget)
    return {"status": "CERTIFIED ARTIFACTS ONLY", "cases": results,
            "semantic": details, "protection": protection, "resource_probes": controls,
            "case_count": len(results), "valid_vector_count": 2 * len(VECTORS),
            "remote_cases": remotes,
            "executed_semantic_vectors": sum(len(r["vectors"]) for r in details.values()),
            "managed_process_count": budget.processes, "parent_owned_bytes": budget.used,
            "process_count_scope": "wrapper launches, excludes nested unittest CLI subcalls",
            "limits": "trusted host fixtures; no arbitrary candidate or paired/live calibration"}


def test_population(row):
    o.test_population(row)


if __name__ == "__main__":
    if len(sys.argv) != 1:
        print("Unsupported arguments: qualification accepts committed fixture cases only.", file=sys.stderr)
        raise SystemExit(64)
    try:
        report = qualify()
    except (o.Unavailable, Refused) as exc:
        print(json.dumps({"status": "UNKNOWN" if isinstance(exc, o.Unavailable) else "REFUSED", "reason": str(exc)}))
        raise SystemExit(2 if isinstance(exc, o.Unavailable) else 1)
    print(json.dumps(report))
