# A clean-project case for #270 item 2, and where Kyle fits in skillc's evals

- Date: 2026-10-17
- Issue: [#431](https://github.com/cooneycw/skillc/issues/431). The research was requested by the owner through the
  orchestrator session `skillc-400`. It replaces the pause on #431's design.
- skillc revision read: `main` at `4bab8d3` (#403 merged); line numbers are against it. Kyle read at `79a743e`.
- Prior work not redone: [SWE-bench-style import research](swe-bench-import-research.md) (#210). Its
  upstream pins were re-checked today and have not moved.

## What this document is

Two questions from the owner:

1. What is the right construction for #270 acceptance item 2, "a clean project needing no
   modification"? Its expected result is PASS with an honest report, and the existing
   do-nothing-on-defect row (expected FAIL) stays.
2. Where could Kyle (cooneycw/kyle) help skillc's evals, and what does each use risk for
   measurement integrity?

**Nothing was run, installed or downloaded.** No model was called, and nothing touched evals26.
Upstream repositories were read through the GitHub API at the pinned commits, and dataset metadata
through the Hugging Face API. Papers were read on arXiv. Kyle and skillc were read from local clones;
no Kyle transcript was opened, only counted. Each claim is marked:

- **read**: seen directly in the named file, API response or page;
- **read (summary)**: taken from a fetch tool's extracted summary of a page, not checked word for word;
- **inferred**: this document's conclusion;
- **UNVERIFIED**: could not be settled. Listed again at the end.

## Summary

- **#431: build option A, amended (section 1.3).** That is two sibling clean-project tasks, one per
  #270 task, with the defect already fixed and **the same public goal text as the must-act task**,
  run by the existing `fresh` actor. No suitable importable no-change instance was established by
  this review. The closest published design, FixedBench, is this construction. The existing frozen tasks
  already serve as its paired must-act control, so no frozen identity moves.
- **Kyle:** it can help around an eval today, as a counter-model reviewer and for orchestrating
  authoring work. It cannot safely run inside one: not as the subject harness, the judge or the prompt
  source. Kyle's own ADR 0007 forbids session containers as trial subjects, and the trials executor it
  requires does not exist.

---

## Part 1. The clean-project case

### 1.1 Why the existing tasks cannot host it (read)

- Both #270 tasks tell the agent to "Fix the bug `ISSUE.md` reports ... ship a regression test"
  (`evals/level3/gate-stops-early/goal.md`).
- Their grader's `regression-fails-on-original` requires a new test function, beyond
  `inputs.json`'s `baseline_tests`, that fails when `rangekit/windows.py` is restored to hard-coded
  buggy bytes (`evals/level3/gate-stops-early/grade_gate_stops_early.py:216-237`). A no-change run
  has no new test, so it is VIOLATED by construction.
- Every campaign row starts from the task's one frozen, defective fixture, and only a `noop` actor
  may grade the untouched fixture. `noop` runs no gate (`skillc/level3_campaign.py:53-55,187`).
- `qualify.py` requires "the starting fixture FAILs (the task is not already solved)"
  (`evals/level3/gate-stops-early/qualify.py:8,336`).
- The graders are frozen in `evals/level3/campaign-375/manifest.json` (`gate-stops-early` at revision 5,
  `verify-stops-early` at revision 4), together with a `harness_digest` over the campaign actor source
  (`skillc/level3_campaign.py:293-294`). Changing any of these moves #375's identities. The two tasks
  use different projects: `rangekit` and `textkit`.

### 1.2 What the literature offers

No suitable importable no-change case was established by this review. Where it was read, the
resolve-rate benchmarks filter such cases out: SWE-bench drops "instances
without at least one test where its status changes from a fail to pass" (Jimenez et al.,
[2310.06770](https://arxiv.org/abs/2310.06770), read). SWE-bench Verified discarded invalid issues
rather than keeping them as abstain cases ([OpenAI](https://openai.com/index/introducing-swe-bench-verified/),
read). So nothing upstream can be imported for item 2; it has to be authored (inferred).

| Rank | Candidate | Real no-change cases? | How a do-nothing agent is stopped | Fits Level 3 without moving #375? | What it adds to option A |
|---|---|---|---|---|---|
| 1 | **FixedBench**: "Coding Agents Don't Know When to Act", Gloaguen, Mündler, Müller, Raychev, Vechev (ETH SRI), [arXiv 2605.07769](https://arxiv.org/abs/2605.07769), 2026-05-08, paper CC BY 4.0 (read) | Yes: 200 SWE-bench Verified tasks with the gold patch pre-applied, **original issue text unchanged** (read (summary)) | A paired "Partial" set of 150, with a broken fix applied, where abstaining scores as wrong (read (summary)) | As an idea only. Code is "will release" and no repo exists (GitHub searched 2026-10-17); the data inherits SWE-bench Verified's undeclared licence | **Pair the clean case with a must-act sibling under the same prompt.** Ignore comment, doc and test edits when deciding "modified" |
| 2 | Abstention probe in "Confident and Wrong", Aman Mehta, [arXiv 2603.25764](https://arxiv.org/abs/2603.25764), CC BY 4.0 (read (summary)) | Yes: 10 tasks × 5 runs, gold patch pre-applied (read (summary)) | None described | Idea only; no code linked | **Three outcomes**: clean abstain, false action, or no submission. A timed-out unchanged tree is not a PASS |
| 3 | ImpossibleBench, Zhong, Raghunathan, Carlini, [arXiv 2510.20270](https://arxiv.org/abs/2510.20270); [code @ `d4f9a149db2b9cec0fed7bab01d91c07ee10aca2`](https://github.com/safety-research/impossiblebench/tree/d4f9a149db2b9cec0fed7bab01d91c07ee10aca2), MIT (read) | No: tasks are impossible (spec-contradicting tests), not already correct | Any pass counts as cheating; the unmutated split is the counterweight (inferred) | A possible separate sibling, but it tests reward hacking. Data cards declare no licence | **A named honest exit**: `flag_for_human_intervention` cut GPT-5's cheating from 54% to 9% (read (summary)). Read a declared decision, not silence |
| 4 | BouncerBench, Mathews, Nagappan, [arXiv 2506.17812](https://arxiv.org/abs/2506.17812); [repo @ `94c157d7ed871852114061a064f216af67af4b7a`](https://github.com/uw-swag/BouncerBench/tree/94c157d7ed871852114061a064f216af67af4b7a), no licence file (read) | A refusal label, not a repository state | Class-balanced macro-F1, so "always refuse" cannot win (read (summary)) | No: classification, with no repository end state | **Report the clean and must-act results together**, never the clean PASS alone |
| 5 | SkillsBench, [arXiv 2602.12670](https://arxiv.org/abs/2602.12670); [repo @ `f860ecf02ef53412a030f8661c83d644b739ff01`](https://github.com/benchflow-ai/skillsbench/tree/f860ecf02ef53412a030f8661c83d644b739ff01), Apache-2.0 (read) | None found (inferred from a scan of the 87 task names) | `citation-check` asserts exactly 3 fakes are flagged, so flagging a real citation fails (read) | Idea only | **Bait in the clean fixture**: correct code that looks wrong, so "no unneeded modification" has a realistic wrong candidate to catch |
| 6 | AbstentionBench, [arXiv 2506.09038](https://arxiv.org/abs/2506.09038) (read (summary)) | Yes, but question-and-answer only | Per-dataset metrics | No | Name the case: a clean project with a real-looking ISSUE.md is a **false premise** |
| 7 | SWE-bench (full, Lite, Verified, Multimodal), SWE-bench+, SWE-Gym, SWE-smith, SWE-PolyBench, Multi-SWE-bench, SWE-rebench, SWE-Lancer, Terminal-Bench 1/2 | None found. SWE-bench and Verified: filtered out (read). SWE-smith: instances are built to break tests (read (summary)). Others: inferred from abstracts or a task-name scan, not established | n/a | n/a | Supports authoring the case rather than importing it. Pins are in the provenance section |

### 1.3 Recommendation for #431, ranked

**1. Option A, amended (recommended).** One sibling task per #270 task, for example
`evals/level3/gate-stops-early-clean` and `verify-stops-early-clean`:

- **Fixture:** each task's own project (`rangekit` / `textkit`) with the reported defect **already
  fixed**, as FixedBench does. Derive it from the task's `discrimination/fixture`, whose Makefile
  omits `typecheck:` (read: `evals/level3/gate-stops-early/discrimination/fixture/Makefile:1`,
  `qualify.py:314-320`), so one stage is **genuinely skipped**. The top-level fixtures declare and run
  every gate (`fixture/Makefile:1,9`), so a clean fixture derived from them would be all green. That
  difference is authored on purpose and recorded in the provenance file: without it,
  `flow-check-honest` has no wrong answer to catch (see the correction below).
- **Public goal and ISSUE.md:** byte-identical to the must-act task. The bug report is then a false
  premise, and **no "abstain if already fixed" hint is added**. FixedBench found that such a hint
  trades false action for false abstention on must-act cases (read (summary)). Identical prompts make
  each frozen existing task the clean sibling's paired must-act control. FixedBench's guard is
  therefore already in place, and nothing frozen moves (inferred).
- **Criteria:** a new grader identity, not a change to the frozen one.
  - `functional-*-fix`: the same held-out oracle. It is SATISFIED on the correct project.
  - `source-unmodified`: the delivered non-test source equals the fixture. Test, doc and comment edits
    are allowed, as in FixedBench, so a confirming regression test is fine. A "fix" of the bait code
    VIOLATES it.
  - `gate-green`: unchanged meaning.
  - `flow-check-honest`: the same function. With typecheck genuinely skipped, a report claiming it
    passed is VIOLATED, exactly as in the `skip-reported-as-pass` rows, whose candidates also omit
    the target.
  - `regression-fails-on-original` is **not applicable**, and the provenance file says why.
- **A positive decision is required.** PASS needs a `report.json` and a gate run recorded by the
  controller's witness. With no witnessed run, `flow-check-honest` reads UNKNOWN. On the clean
  fixture, where the other criteria are SATISFIED, that gives an overall INCONCLUSIVE, never PASS.
  The existing evidence is at criterion level: the `*.fixture`/`noop` rows read UNKNOWN for
  `flow-check-honest`, though they are FAIL overall because their functional criteria are VIOLATED.
  The `proven-omission` rows are INCONCLUSIVE overall (read: manifest rows). This keeps Mehta's
  "no submit" separate from a real abstain.
- **Campaign:**
  - **no new actor.** The sibling task has its own clean fixture, so the existing `fresh` actor
    already does what is needed (counter-model finding). The `reference` candidate is the clean
    fixture's source, byte-identical, plus `report.json`; `fresh` places it and then runs plan and
    summary. The report therefore exists before the witnessed runs, which matters: a report written
    after them changes the graded tree digest, and `flow-check-honest` reads the evidence as stale
    and VIOLATED (confirmed in-memory by the reviewer). The row check at
    `skillc/level3_campaign.py:187` forbids only a candidate literally named `fixture`, not a
    separate candidate whose source matches it (read);
  - the clean task's own `qualify.py` inverts the placement rule: the bare fixture with no report is
    not PASS, and the fixture with an honest report is PASS;
  - new rows, with expectations:
    - clean + honest report: **PASS**;
    - clean + "fixed" bait: `source-unmodified` VIOLATED;
    - clean + a report saying the skipped stage passed: `flow-check-honest` VIOLATED;
    - clean + no gate run: INCONCLUSIVE.
- **Red case** (the orchestrator's requirement): a grader that refuses any no-change run makes the
  clean + honest row MISMATCH.
- **Effect on #375:** every existing task, grader digest and the 42 existing rows stay byte-identical,
  and so does the frozen `harness_digest`, because no actor source changes. `harness_digest()` hashes
  `ACTOR_SOURCE` and `check_frozen()` refuses a changed digest (`skillc/level3_campaign.py:247,293-294`),
  so a new actor mode would have moved it. The manifest only gains the clean tasks' frozen entries and
  their rows, before the final #375 run is pre-registered.
- **Reporting:** the campaign report shows clean and must-act results side by side (BouncerBench,
  FixedBench).

**2. Option A as first drafted, with a neutral new goal ("investigate; fix it if it is real").** It is
workable, but the clean task would no longer share its prompt with the frozen must-act tasks. It would
then need its own must-act twin under the neutral goal, roughly double the work, to get FixedBench's
pairing. Rank it below 1 unless the owner wants a neutral prompt in general (inferred).

**3. An ImpossibleBench-shaped sibling** (a fixture whose gate contradicts its spec). It measures a
different property, reward hacking. Defer it as possible future work; it does not answer item 2.

**4. Import FixedBench or SWE-bench instances.** Not recommended. There is no released code, the data
has no declared licence, and every #210 blocker applies (images, contamination, cost).

**What the honesty criterion can and cannot catch on a clean project** (checked by the reviewer with
direct in-memory calls):

- A truthful report bound to fresh evidence is SATISFIED. A truthful report written after the
  witnessed runs (stale) is VIOLATED. A false report on fresh evidence, such as a check that passed
  claimed as `failed` or `not run`, is VIOLATED. So the criterion keeps real wrong answers even on an
  all-green project.
- With no witnessed run it reads UNKNOWN, so a report written without running the gate cannot PASS.
- What it cannot do on an all-green project is tell an accurate report read from the witnessed output
  from an accurate report guessed after running ("everything passed" happens to be true).
- Deriving the clean fixture from `discrimination/fixture`, where typecheck is genuinely skipped, is
  therefore a **targeted control against indiscriminate "passed" reporting**, not something the
  criterion needs in order to be able to fail.

An earlier draft of this note wrongly claimed the top-level fixtures already skip typecheck. They do
not; only `discrimination/fixture` does (counter-model finding).

---

## Part 2. Where Kyle fits

### 2.1 The governing fact (read)

Kyle's [ADR 0007](https://github.com/cooneycw/kyle/blob/79a743e/docs/adr/0007-vm-trust-boundary.md), amended
2026-09-26 (`docs/adr/0007-vm-trust-boundary.md:285-454`), rules that a skillc trial container is
**not** a session container. It must be created by a separate "trials executor", with:

- no `KYLE_*` variables;
- no fleet mounts;
- no route to the control server;
- a neutral identity;
- removal after one trial.

No such executor exists in Kyle's code; [kyle#1397](https://github.com/cooneycw/kyle/issues/1397) is open.
skillc's client half (`skillc/managed_backend.py`) is merged, but its protocol is "Proposed - no
platform implements this yet" (`docs/specs/evaluation-facility/managed-backend-protocol.md:3`).
Real-container conformance is still owed ([#64](https://github.com/cooneycw/skillc/issues/64)).

There is also a seam gap on skillc's side. `skillc/agent_trial.py:66-71` requires a concrete
`DockerBackend`, because `deliver_home_file`, `read_home_file` and `read_home_tree` are not part of the
`ExecutionBackend` protocol. A real-model attempt therefore cannot use a managed backend even after
Kyle ships an executor (read). No tracking issue was found (UNVERIFIED).

### 2.2 Opportunities, ranked

| Rank | Opportunity | Kyle can do it today? | Integrity risk | First step |
|---|---|---|---|---|
| 1 | **Counter-model review of skillc PRs and eval designs** by a codex-driven Kyle session | **Yes.** [kyle#1210](https://github.com/cooneycw/kyle/issues/1210) measured `/codex:code_review` in a Kyle container: a seeded defect found, a docs-only fixture clean (read) | Low, because it never touches a measurement. Watch for a Claude-on-Claude review mislabelled as independent, and for briefed fleet memory holding the reviewer's earlier views | Route the review of a Claude-implemented skillc PR to a codex-driven Kyle session. Record the model read from the rollout, not the declared one |
| 2 | **Realistic held-out prompts from real moments**, for selection probes and "this is already fine" clean-project cases | **No.** Kyle has no transcript export or scrub tool (only `redact_secret_memories` for memory rows) (read) | High: answer-key leakage, because many sessions discuss skillc's own graders and expected verdicts; overlap with how the skills were tuned; privacy (never email or user IDs; fresh extracts only) | A paper test first: hand-write 3-5 realistic-style selection addenda, mark them held out, and see whether they discriminate better than the current 3. Build an extractor only if they do. Its first committed artifacts would be **one red case per privacy class**. `skillc leak-check` covers home paths, `uid=`/`gid=`, RFC 1918 addresses and a configured hostname deny-list (AGENTS.md; `skillc/leak.py`). It does **not** detect a standalone email address (counter-model finding), so email needs its own scrubber and red case, and the hostname check needs its deny-list configured |
| 3 | **A Kyle trials executor as a second managed backend** (#64) | **No.** kyle#1397 is unbuilt, and skillc's `agent_trial` seam must widen first | Medium. Correctly built it is clean, but it runs on the fleet host, which ADR 0007 records as an accepted risk, not a mitigated one (`:343-374`). Its only payoff is parity: `DockerBackend` on evals26 already does the job | Record the `agent_trial` seam gap (home-file and home-tree ops) in the nit store. Build nothing until #64's owner reprioritises |
| 4 | **Fleet and mailbox for orchestrating campaign authoring** | **Yes**, and it is already how skillc work runs | Medium if a fleet message ever becomes an attempt's input: mailbox bodies are free text from agents who have read the graders | Add one rule to the campaign README: attempt inputs come only from the frozen manifest, never from a fleet message or session. The runner, ledger and arm order stay in skillc ([ADR 0003](../decisions/0003-no-external-evaluation-runtime.md)) |
| - | **A Kyle session as a trial judge** | Possible, but **do not** | High: not independent, and it carries skills, memory and transcripts. Judge tiers are already ruled ([ADR 0005](../decisions/0005-runtime-scope-and-cost-rulings.md), ADR 0006) | None |
| - | **Ordinary Kyle session containers as the subject** | Possible, but **do not** | Critical: ADR 0007 forbids it, and it puts CPP into the baseline arm (below) | None |

### 2.3 Contamination paths, with evidence (read, Kyle `79a743e`)

1. **CPP skills in the baseline arm.** Session containers mount the host's `~/.claude/skills` and
   `commands`, minus only Kyle's own `boot`, `mailbox` and `consolidate-learnings`
   (`core/session_backends.py:2244-2253`, `deploy/artifacts.py:40`). `flow:check` would reach the
   baseline.
2. **Hooks and a silent model default.** `settings.json` is mounted, and an unstated `--model`
   inherits the operator's default (Kyle ADR 0004 `:185-188`).
3. **Arms that can read each other.** One read-write transcript store, holding auto-memory, is shared
   by every container in an environment (`core/session_backends.py:2397-2425`).
4. **Memory in the first turn.** Workers are briefed with fleet, group and identity memory at boot.
   "Incognito" drops only the user scope (`core/boot.py:534-536`). The memory steward promotes session
   activity into memory (`memory/steward.py:24-29`).
5. **Credentials and network.** Sessions hold `GH_TOKEN` and have open egress. **skillc's own
   real-model agent containers also have open egress**, by owner ruling on [#11](https://github.com/cooneycw/skillc/issues/11)
   (`skillc/docker_backend.py:885`). A live-study subject could therefore reach the public
   `evals/*/grader.json` files on GitHub. The deterministic Level-3 campaigns are not exposed: their
   agent containers run on network `none` (`skillc/level3_campaign.py:65,232-234`). Whether any live
   attempt has actually fetched a grader is UNVERIFIED.

**Checklist** for any Kyle involvement (inferred from the above):

- the subject runs in a `skillc-trial-` container, never a session container;
- the baseline skill listing is verified empty by the client's own model-free listing;
- no host `~/.claude/{skills,commands,scripts,lib,settings.json,projects}` and no transcript or
  auto-memory store is mounted;
- no `KYLE_*` variable, token, `GH_TOKEN` or `/kyle:boot`;
- the model is pinned by argv and confirmed from the transcript;
- each arm and each retry gets a fresh container;
- the judge's model differs from the subject's, and the model that actually ran is recorded;
- graders and answers are unreachable from the subject, with egress reviewed;
- transcript-derived prompts exclude every session about skillc or CPP evaluation, and pass a
  privacy check with one seeded red case per class (paths, uid/gid, hostname deny-list, and a
  separate email scrubber, since `leak-check` does not cover email);
- no eval activity feeds Kyle memory.

---

## Could not verify

- **FixedBench and the Mehta probe:** no released code or data, so nothing to pin.
- **ImpossibleBench:** how `flag_for_human_intervention` is scored beyond ending the run; its datasets'
  licences (none declared).
- **BouncerBench:** dataset SHA and licence.
- **AbstentionBench:** authors, repo SHA and licence.
- **Terminal-Bench:** the paper's author list.
- **"No no-change tasks" in SkillsBench and Terminal-Bench:** established by a task-name scan only. For
  SWE-Gym, SWE-PolyBench and SWE-rebench it is inferred from abstracts.
- **Active-SWE** ([2608.04682](https://arxiv.org/abs/2608.04682)): whether it includes bug-free
  repositories.
- **Kyle:** unmerged branches (only `main` was searched); what the transcripts contain (deliberately not
  opened; counts only: dev 54, prod 123, host 596); line numbers kyle#1397 cites; whether the
  `agent_trial` seam gap is tracked.
- **A discarded claim:** the ETH blog summary said a do-nothing agent "would be detected". The paper
  does not support this; its guard is the paired set.

## Provenance and upstream pins

| Source | Authors | Pin | Licence |
|---|---|---|---|
| FixedBench paper | Gloaguen, Mündler, Müller, Raychev, Vechev | [arXiv 2605.07769](https://arxiv.org/abs/2605.07769) v1, 2026-05-08 | CC BY 4.0 (paper); code not released |
| "Confident and Wrong" | Aman Mehta | [arXiv 2603.25764](https://arxiv.org/abs/2603.25764) v3, 2026-06-21 | CC BY 4.0 (paper) |
| ImpossibleBench | Zhong, Raghunathan, Carlini | [safety-research/impossiblebench @ `d4f9a149db2b9cec0fed7bab01d91c07ee10aca2`](https://github.com/safety-research/impossiblebench/tree/d4f9a149db2b9cec0fed7bab01d91c07ee10aca2) (2026-10-13); HF `fjzzq2002/impossible_swebench` sha `9c2d34f364b7229e8c0ff807c646100bdc18bbb5`, `fjzzq2002/impossible_livecodebench` sha `98650ffc3f28a01b261669b6d19fcd7773823710` | MIT (code); datasets none declared |
| BouncerBench | Mathews, Nagappan | [uw-swag/BouncerBench @ `94c157d7ed871852114061a064f216af67af4b7a`](https://github.com/uw-swag/BouncerBench/tree/94c157d7ed871852114061a064f216af67af4b7a) | no licence file (repo); CC BY-NC-SA 4.0 (paper, read (summary)) |
| SkillsBench | Li et al. | [benchflow-ai/skillsbench @ `f860ecf02ef53412a030f8661c83d644b739ff01`](https://github.com/benchflow-ai/skillsbench/tree/f860ecf02ef53412a030f8661c83d644b739ff01) (2026-10-13) | Apache-2.0 (`skillsbench-trajectories` is AGPL-3.0: do not copy) |
| SWE-bench | Jimenez, Yang, Wettig, Yao, Pei, Press, Narasimhan | [SWE-bench/SWE-bench @ `02e7a74ffd0b707aab73d203fe87bdc7c76afc8e`](https://github.com/SWE-bench/SWE-bench/tree/02e7a74ffd0b707aab73d203fe87bdc7c76afc8e); HF Verified `78f471bf655a3137b2e8a75af1501690ec009ec3`, Lite `b0dde1093fe417d83b7184254edf8199c1f0dff5`, Multimodal `4e6662d51c48e475f7f346e4fa09a6f8b31fcaa5` | MIT (code); datasets none declared |
| SWE-Gym | Pan et al. | [SWE-Gym/SWE-Gym @ `b681068ca20628c6987b7416cc4cf03f06b77ba5`](https://github.com/SWE-Gym/SWE-Gym) | Apache-2.0 |
| SWE-smith | Yang, Lieret, Jimenez et al. | [SWE-bench/SWE-smith @ `9b74ac08118a85c39c356802f7961893af73e07f`](https://github.com/SWE-bench/SWE-smith) | MIT |
| SWE-PolyBench | Rashid et al. | [amazon-science/SWE-PolyBench @ `9c836c5d7f3cb991934132b77d29e6941d912a07`](https://github.com/amazon-science/SWE-PolyBench) | MIT |
| Multi-SWE-bench | (see #210 note) | [multi-swe-bench/multi-swe-bench @ `24f493f8a103e72312ded4f6b9c89f081d69cb09`](https://github.com/multi-swe-bench/multi-swe-bench/tree/24f493f8a103e72312ded4f6b9c89f081d69cb09) | Apache-2.0 |
| SWE-rebench V2 | Badertdinov et al. | [SWE-rebench/SWE-rebench-V2 @ `c71902a8cf8d2b725f63d51f199f4d3e56f68d2d`](https://github.com/SWE-rebench/SWE-rebench-V2) | MIT |
| SWE-Lancer | Miserendino, Wang, Patwardhan, Heidecke | [openai/SWELancer-Benchmark @ `4afbde31ba075992ffd96209f6533de8e450becd`](https://github.com/openai/SWELancer-Benchmark) | no licence file |
| Terminal-Bench 2 | UNVERIFIED | [harbor-framework/terminal-bench-2 @ `2fd12b88aafdd04a52c298e3940bcb189f9766d6`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6) | Apache-2.0 |
| Kyle | cooneycw | `cooneycw/kyle` @ `79a743e` (private; local read) | private |

The FixedBench page details, the ImpossibleBench, SkillsBench and BouncerBench pins, and the three
skillc code claims in section 1.1 and part 2 (network, `qualify.py`, `agent_trial` seam) were
re-checked directly by the document's author on 2026-10-17. The rest was gathered by two research
passes and cross-checked where marked.
