# Coder Eval → skillc evaluation-facility contract handoff

For peer thread `01a0b96d-ef27-70c2-84c0-5335c43d99bc`, in the owner-authorized exchange. Documentation/research only: no skillc draft edits, CPP edits, dependency installation, repository-code execution, or paid trials by this reviewer.

## Revision and reproducibility

- Repository: https://github.com/UiPath/coder_eval/
- Inspected revision: `d960de1c433a1b050d2509f04d94a60e3cabaaf0`; package version `0.12.4`, requires Python 3.13+.
- Durable bare source snapshot: `<operator-home>/Projects/research/coder-eval-scan-2026-09-20/source.git`.
- Initial broader handoff: `<operator-home>/Projects/reports/coder-eval-cpp-handoff-2026-09-20.md`.
- Read any cited source without executing it: `git --git-dir=<operator-home>/Projects/research/coder-eval-scan-2026-09-20/source.git show HEAD:src/coder_eval/models/results.py`.
- Source references below use this exact revision. “Code-verified” means static inspection of implementation, not a successful runtime trial. “Inference” and “proposed” are explicitly separated. This is a focused inspection, not a complete security audit.

## 1. Installed skills and adapter contracts

**Code-verified:** Claude's adapter passes local `plugins` to `ClaudeAgentOptions`, uses the task working directory, and sets `setting_sources` to `["project"]` when not explicitly supplied (`agents/claude_code_agent.py:1185-1208`). Config also exposes `claude_settings`; `models/agent_config.py:240` explains project MCP discovery. The adapter preserves Claude's default preset and appends configured instructions unless explicitly placed in replacement mode (`claude_code_agent.py:1223` onward).

**Code-verified:** Codex's `_setup_skills` stages discovered `<name>/SKILL.md` directories under the task's `.agents/skills`, ordinarily as symlinks with copy fallback. It scans both the supplied source and a nested `skills/` directory. An existing target wins; missing sources and zero linked skills warn rather than necessarily fail (`agents/codex_agent.py:1090-1180`). Its configured `system_prompt` becomes `developer_instructions`, which is a different integration mechanism from native skill discovery (`codex_agent.py:1372-1376`).

**Code-verified:** the `skill_triggered` checker credits an explicit Skill call or a `skills/<name>/` substring in string tool parameters (`criteria/skill_triggered.py:42-62`). It does not prove content was read successfully or followed. Treat it as a weak observation, not an installation receipt or outcome proof.

**CPP-specific observed fact:** CPP's own README identifies `.claude/commands/<family>/*.md` as canonical and retires its plugin marketplace distribution. Its installation includes helpers/hooks and a separate generated Codex skill surface. A `plugins: [{path: CPP_ROOT}]` configuration is not, by itself, evidence of a faithful CPP installation.

**Proposed skillc boundary:** separate `prepare_subject` / `verify_installation` from `run_trial`. The subject adapter should declare installation mode (native commands, native skills, plugin, or deliberate prompt treatment), immutable source revision/digest, expected entrypoints, transitive helpers/references, configuration layers, allowed writes, owned/deferred surfaces, and external dependencies. Return a machine-readable installation receipt produced by the adapter/controller, including resolved paths and content hashes. Fail preflight if a required surface is absent; a source checkout existing is insufficient. Verify one real native discovery/invocation canary and negative/absence controls. Do not quietly substitute prompt injection when native installation fails.

**Proposed comparison rule:** use clean homes/workspaces, pin non-subject settings, and make installation mode part of experiment identity. A baseline must prove subject absence. Disabling project settings indiscriminately may also disable the feature being measured; declare settings explicitly instead of calling `setting_sources=[]` universally correct. Symlink staging requires accessible immutable targets and collision checks; it is not a content snapshot.

## 2. Result/event schemas and ownership

**Code-verified schema:** `models/results.py` defines:

- `TaskConfigRecord` (line 49): resolved config, original YAML, source file, and per-field config lineage. Lineage is config-layer attribution, not authenticated producer provenance.
- `CriterionResult` (line 58): criterion type, score in [0,1], details/error, `evaluation_status` (`evaluated`/`not_evaluated`), threshold, gating, and `result_kind` for subtype preservation. The base permits extra fields.
- `EvaluationResult` (line 552): task/variant/agent/model identity, start/end/duration, nullable `setup_ms` and `grading_ms`, final status, nullable weighted score, criteria results, iterations, environment info, SDK/agent config, workspace location, config snapshot, and token usage.
- `RunSummary` and aggregate models: run/suite/variant/experiment reporting. Some summaries intentionally denormalize rows into dictionaries; do not treat every report field as a strict transport schema.

**Code-verified event implementation:** `streaming/events.py` uses Pydantic events with task/time/thread/parent-thread identity, turn identifiers, model names, and distinct tool/turn/agent terminal statuses. The adapter emits execution events from `communicate()`. `EventCollector` reduces tool-end events into `TurnRecord` and takes terminal usage/message payloads from `AgentEndEvent`; tool IDs are deduplicated with last result winning (`streaming/collector.py:48-82`). Nested-thread identifiers exist in the schema, but the collector comment says nested subagent events are not yet emitted and it ignores non-main events. Do not promise complete subagent event coverage from the schema alone.

**Code-verified transport:** Docker forwards event envelopes over container stdout, framed with the sentinel `\x1ecoder-eval-stream\x1e:` and JSON `{cls, data}`; parsing selects an allowed event class and validates its data (`streaming/wire.py`). This is collision avoidance and shape checking, not authentication.

**Code-verified persistence:** in-container orchestration writes `task.json`; the host reads it from a writable bind-mounted output directory (`isolation/docker_runner.py:1303-1306`, `843-876`). Host reporting/aggregation then consumes the result. `path_utils.write_text_atomic` uses a unique exclusive/no-follow temporary file and replacement to avoid torn writes and temporary-file symlink attacks. Those properties do not establish who caused the bytes to be written.

**Documented output layout, consistent with inspected models:** `run.json`, `experiment.json`, per-variant `variant.json`, and `<variant>/<task>/<NN>/task.json`; detached grading can preserve `task.execute.json`; judge transcripts have sibling files. See `docs/REPORT_SCHEMA.md`. `NOT_GRADED`, missing cost, and unavailable measurements have explicit representations and must remain distinct from success/zero.

**Proposed skillc ownership contract:** controller owns trial identity/lifecycle and expected trial inventory; execution adapter owns raw transport observations; exporter owns artifact capture; verifier owns verdicts; aggregator owns derived comparisons. The subject agent's final answer owns none of those authoritative facts. Keep Coder Eval's raw record plus a versioned skillc envelope rather than depending on its evolving schema as skillc's permanent public API. Suggested envelope: schema version, trial/attempt ID, case revision, subject digest, installation receipt digest, variant, runtime/model/config/image identities, raw evidence manifest, exit/termination observation, verifier version and grader digest, artifact digest, and final disposition with explicit missing-evidence reasons.

## 3. Independent verification and evidence integrity

**Code-verified useful protections:**

1. `ContainerContext` requires every dispatch field and forbids extras, using strict booleans/integers. Fields include variant, replicate, config lineage, preservation, grade/regrade, source YAML, host task path, workspace, and authored sandbox (`models/container_context.py`).
2. The Docker result reader validates `EvaluationResult` and compares the returned `environment_info.container_contract` for exact equality against staged input. Missing/malformed/mismatched records become synthetic ERROR records; mismatched records are quarantined (`docker_runner.py:843-913`). This is useful compatibility and dispatch-mismatch detection.
3. Reference contents are digested before evaluation and checked for modification before grading (`orchestrator.py:1396`, `1429`; `path_utils.py:88`). Detached grading rejects a changed recorded reference digest. If the digest is absent, it warns and proceeds (`orchestration/regrade.py:472-513`).
4. Detached grading refuses embedded executable capabilities from a recorded config without explicit opt-in, or accepts an explicitly operator-supplied task instead (`regrade.py:309-347`). Workspace resolution checks containment, including symlink escape cases (`regrade.py:425-455`).
5. Agent judges force `setting_sources=[]` and preserve an ignore floor for `.claude`, `.mcp.json`, and `_reference`; verdicts come through a typed `submit_verdict` tool channel with per-invocation capture (`criteria/agent_judge.py:240-276`, `evaluation/verdict_tool.py`). The capture accepts the last submitted verdict; it is not an enforced exactly-one-call protocol.

**Inference / limit, not a demonstrated exploit:** these checks do not establish adversarial evidence authenticity. A container-contract echo validates equality, not an independent attestation that the workload obeyed it. The inspected context carries no attempt nonce or artifact digest. A correctly shaped result or sentinel-framed event can still be untrue; there is no authentication step in the inspected result/event readers. Agent and grading paths execute inside the eval container with shared output surfaces. Do not describe this as a separately privileged, tamper-proof grader boundary. No end-to-end forgery exploit was executed in this review.

**Code-verified operational corrections:**

- At this pinned revision, Codex `_build_thread_options` unconditionally sets `Sandbox.full_access` (`agents/codex_agent.py:1381-1387`). Do not rely on older prose describing host Landlock confinement. Docker is needed for the proposed OS boundary.
- The Docker source mounts copied task/reference trees read-write to support permission windows, and detached grading can mount the executed workspace read-write without copying (`docker_runner.py:1307-1323`). Older doc wording about a tmpfs reference mask does not describe this source path.
- The default agent judge has Bash and bypassPermissions with evaluator credentials (`models/criteria.py:56`). Untrusted-text framing and typed verdicts do not make it safe to execute subject-controlled code with grader secrets.
- `run_command` actually executes a command and checks exit/stdout (`criteria/run_command.py:64-97`). That is useful evidence only if the command, checker, dependencies, and output channel are controlled appropriately; executing a subject-replaced checker proves little.

**Proposed independent verifier contract:** terminate the subject and confirm process cleanup; capture an immutable artifact snapshot with path/type/size/content hashes; verify identities against a controller-owned trial ledger; run the pinned grader and held-out fixtures in a fresh separate environment on a disposable copy. Keep original artifacts unchanged. Supply trusted grader config from outside the run directory. Reject missing provenance required by the skillc protocol instead of inheriting upstream permissive legacy fallbacks. A digest stored beside data in the same subject-writable directory is not a trust anchor; bind it to the controller's protected record/channel. Cryptographic signatures are optional for a single trusted controller, but become relevant across administrative boundaries.

**Proposed verifier controls:** known-good output passes; wrong output with forged success prose/JSON fails; a stale record from another attempt fails; changed reference/checker and subject-modified tests fail; a no-op checker or bypassed invocation is detected; truncated output/crash/missing records remain inconclusive/error; path traversal/symlink escape is refused; prompt injection in generated artifacts never becomes grader instructions. Retain all planned attempts and explicitly classify infrastructure, execution, verification, and task failures. Successful parsing, process exit 0, a model claim, and independently verified success must be distinct events.

## 4. Reuse decision and adapter gaps

| Reuse candidate, verified or documented in pinned source | skillc responsibility still required |
| --- | --- |
| YAML schemas and task/config resolution | Stable generic goal/case interface and six-level taxonomy |
| Existing agent adapters and native local-skill mechanisms | CPP installation adapter, canaries, dependency closure, clean baseline proof |
| Docker orchestration, limits, error retention | Stronger subject/verifier separation, declared credentials/network/mount policy, trusted process cleanup evidence |
| Repeated A/B variants, config lineage | Matched case inventory, scheduling/order policy, immutable subject revisions and experiment comparability rules |
| Timing/token/cost/event collection | Independent trial identity, completeness checks, missing external/MCP/delegated spend attribution |
| Deterministic criteria, verdict models, execute/evaluate split | Controller-owned graders/controls and artifact-bound verdicts; avoid blind trust in imported task.json |
| JSON/Markdown/HTML/JUnit reports and dashboard | Versioned report-back contract, integrity checks, retention, and level/goal aggregation semantics |

**Recommendation:** evaluate Coder Eval as a replaceable execution/measurement backend behind skillc contracts. Its `execute` plus separately controlled grading path is a promising seam to prove with a later canary, not a verified ready-made trusted verifier. Preserve CPP's existing delivery fixtures and the September 19 eval research; do not replace them merely to match a runner's format. Accept runner reuse only after installation, failure accounting, and forged/stale-evidence controls work through the complete adapter path.

No implementation or live canary has been performed. No edits were made to the receiving session's README, PLAN, spec/protocol/review, or ADR files.
