# #557: audited historical B/N/P repeat

**Run completed 2026-10-24: 18/18 planned slots captured and audited; 0/18
primary PASS.** Each arm has six historical task-grader failures. All captured
runbooks are byte-identical to the starting fixture. The provided arm opened
`flow-auto` in 6/6 attempts and `flow-check` in 0/6; the natural arm opened an observed skill in 0/6 attempts. These results do not establish
a CPP defect or benefit: the preserved revision-1 wording is ambiguous about
renumbering the approved text, while its grader requires unique step numbers.

This is new experiment `calibration-0d206a11`, not a reconstruction of historical
`calibration-09960aea`. The original [report](../calibration-203-c3/report.md)
remains historical and unchanged. No retry, replacement attempt, added arm or
API judge invocation was made. The approved process exited 0; that exit means
accounted execution, not task success.

## Outcomes and observations

| Arm | Planned/captured | Primary PASS / FAIL | Any skill opened | `flow-auto` opened | `flow-check` opened | Mean agent seconds | Mean reported tokens |
|---|---|---|---|---|---|---|---|
| baseline | 6 / 6 | 0 / 6 | 0/6 | 0/6 | 0/6 | 25.057 | 78,819.8 |
| natural | 6 / 6 | 0 / 6 | 0/6 | 0/6 | 0/6 | 23.076 | 97,976.3 |
| provided | 6 / 6 | 0 / 6 | 6/6 | 6/6 | 0/6 | 42.855 | 269,039.5 |

`named_opened=6` in the controller report means at least one of the two named
skills, not both. All observations were confirmed against exactly one retained
transcript. Skill-read observations use the existing transcript heuristic;
they do not prove that a workflow was followed or that a skill caused an outcome.
Installation readiness is **UNKNOWN in all 18 stored results**, reported beside
the primary endpoint and never promoted from a task outcome or skill read.

All 18 have the same criterion pattern:

| Historical criterion | SATISFIED | VIOLATED |
|---|---|---|
| `report-verdict` | 0 | 18 |
| `one-section-per-step` | 0 | 18 |
| `approved-content-present` | 18 | 0 |
| `other-content-preserved` | 18 | 0 |

Every captured `report.json` says `intact`; every captured runbook retains
steps `1, 2, 3, 4, 5, 5`. The grader rejects that pair while accepting the
approved and other content. This is a reproducible **historical grader
distinction**. Revision 1's public goal asks to preserve the exact approved
change without explicitly authorizing the renumbering the grader expects.
Therefore all 18 failures are ambiguity-bounded measurements; how many would
be caused by ambiguity versus agent decisions is unresolved. Zero attempt or
grading-infrastructure failures were observed; no causal CPP failure attribution
is established. A floor in all arms cannot show generalized improvement or
ineffectiveness.

## Exact inputs and authorization

| Identity | Value |
|---|---|
| Approved canonical declaration | `sha256:e89f5ae9fd71e69a60701bce8295036c0c0c06b2276188caea92e635956980ee` |
| Frozen approval checkout | `1c76a4d5dc3944ab96025ff56290413b75a5c31a` |
| Reviewed controller source | `5f302a0619dfc88a53025bd177489214353eed0f` |
| Retention prerequisite | `c80455538d4412391a375b76202f8c4ec6338be7` (PR #559, bounded #547 slice) |
| Historical task source | skillc `fc02838`, tree `2321b8cfd1dc45ce10449e87df2e373a02a2629c`, revision 1 |
| Goal | `sha256:dd288ba5f15f17cf824de881ba86220b4e4d848b69343072fd070a76f5c701c4` |
| Grader | `sha256:c35cc7f666ac84858640d114804ac3db546dd8a501213ba6dcc7470516050523` |
| Delivered fixture | `sha256:22ba733867862b536a7064596a4800e158494b03d3c2c613cb8518c4a2a62c4f` |
| CPP collection | `85e9b03ad2af1c41020ff6d92d36fa257bdacd2b`, full `cpp-codex`, no profile |
| Replacement image | `sha256:b9816879e22d1f62dc6b8614c787e7666c1d9f438437c3d03d3c622513d1a563` |
| Actual client/model/effort | `0.157.1` / `gpt-6-astra` / `high`, re-derived from all 18 retained transcripts |
| Schedule | six per B/N/P, seed `20261005`, original order, 1200 s per attempt / 21600 s schedule cap |

The owner requested the original 18-attempt repeat. The wave orchestrator
reviewed and authorized the exact declaration under delegated authority; the
actual approval was recorded at `2026-10-24T22:34:01Z`. The owner was not
represented as personally reviewing the digest. Only the approval field
changed after the exact ruling, so the canonical identity remained unchanged.
The experiment used its own locked environment and fresh bytecode cache.
Subsequent publication-branch merges did not enter its frozen runtime.

The original image is unavailable; this is an explicit replacement. The current
controller and provider state also differ from the original run. Task revision 2
remains untouched. These differences and revision-1 ambiguity bound historical
comparability. This development task is not held out, and tuning against these
results would not create fresh effectiveness evidence.

## Retention, joins and audit

The complete private source remains under the declared durable store
`~/.local/share/skillc/calibration-557-repeat`, run
`20261024T223608Z-decc0b`, experiment `calibration-0d206a11`. Preparation,
authorization, controller log and population evidence are separately retained.
No private transcript text or machine-specific path is published here.

The post-run audit verified all 18 unique planned identities and seeded order,
all 134 content-addressed objects (6,696,636 bytes), 162 artifact references and
90 observation objects. Each attempt retains five complete streams: client
events, client stderr, client transcript, egress proxy log and process lifecycle.
Prompt/canary delivery, client/model/effort, token counters and skill reads were
re-derived from transcript bytes and matched the saved observations. The
controller report was rebuilt identically from the retained source. The
original ledger, records, journals and objects were unchanged by audit.

A disposable unmodified object was accepted and its corrupted twin refused by
the production object reader. The committed bad record fixture was refused;
the actual source passed `check-records` with 85 records in one bundle and zero
structural/binding errors. That check establishes structure and internal
consistency, not producer authenticity or behavioral truth by itself.

**Declaration-linkage limit:** this supported legacy calibration stores only
arm/repeat/position in immutable configuration. Its approved declaration is
separately retained at the frozen Git commit and in the private store. The audit
explicitly joined its schedule, case/grader/client/image and subject pins to the
ledger and re-derived observations; it does not claim that the core ledger
embedded the whole declaration. The limit is recorded in the
[Nit Store](https://github.com/cooneycw/skillc/issues/20#issuecomment-6390540770).

All 18 proxy logs match the declared allowlist and re-derived summaries;
252 allowed provider connections and 18 denied non-allowlisted telemetry
connections were recorded, with no upstream failure. All 18 credential
stewards confirmed withdrawal and stop. No guard stop, bypass, other model,
or server-side tool use was observed. All 18 workspace removals and backend
teardowns were confirmed. These are the recorded containment/eligibility facts,
not a claim that readiness became SATISFIED.

## Time and usage

Summed slot wall time: **946.704 s**; agent execution: **545.928 s**;
grading: **49.845 s**; remaining setup/export/teardown/other time: **350.931 s**.
The capture-to-cleanup-confirmation journal intervals total **12.464 s**, already
included in slot wall time; there is no separate exact cleanup timer. Additional
controller/materialization/final-report overhead is not measured by this split.
The 21600-second schedule cap is not an absolute setup/cleanup wall deadline.

Reported cumulative usage is **2,675,014 tokens**, including cached-input usage
where reported. These are subscription quota observations, not a measured
currency charge. Measured monetary cost is **UNKNOWN**, not zero; no API judge
was invoked. No timing or token comparison here claims efficient delivery from
failed tasks.

## All planned slots

All rows are captured task FAIL, with observed `0.157.1` / `gpt-6-astra` / `high`,
complete transcripts, and the same two historical criterion violations.

| Slot | Arm | Trial ID | Attempt ID | Agent seconds | Reported tokens | Transcript bytes |
|---|---|---|---|---|---|---|
| 1 | baseline | `t1-calibration_baseline_1` | `a-6a665d9ffdb3` | 24.092 | 70,540 | 87,370 |
| 2 | baseline | `t2-calibration_baseline_2` | `a-4804389ad794` | 23.104 | 71,012 | 87,997 |
| 3 | natural | `t3-calibration_natural_1` | `a-e59219401131` | 24.308 | 100,409 | 108,188 |
| 4 | baseline | `t4-calibration_baseline_3` | `a-c25dbeda42f9` | 23.687 | 83,137 | 90,902 |
| 5 | natural | `t5-calibration_natural_2` | `a-8ac39d185d9b` | 23.362 | 99,961 | 108,492 |
| 6 | provided | `t6-calibration_provided_1` | `a-cd2c7a7de61f` | 35.913 | 281,221 | 820,665 |
| 7 | baseline | `t7-calibration_baseline_4` | `a-9910332511de` | 24.322 | 82,384 | 87,933 |
| 8 | natural | `t8-calibration_natural_3` | `a-33e3a074fb73` | 24.074 | 85,034 | 102,540 |
| 9 | provided | `t9-calibration_provided_2` | `a-1da9c71eb6b5` | 41.512 | 296,660 | 860,547 |
| 10 | provided | `t10-calibration_provided_3` | `a-9f97c35241ab` | 56.597 | 300,297 | 891,513 |
| 11 | natural | `t11-calibration_natural_4` | `a-95ca2d8b76d9` | 21.981 | 101,061 | 103,655 |
| 12 | provided | `t12-calibration_provided_4` | `a-6080c0c0cbdc` | 47.044 | 303,108 | 954,046 |
| 13 | provided | `t13-calibration_provided_5` | `a-c5139d389d36` | 39.379 | 184,110 | 775,517 |
| 14 | natural | `t14-calibration_natural_5` | `a-296bc1df27ca` | 23.853 | 100,477 | 108,842 |
| 15 | natural | `t15-calibration_natural_6` | `a-b5e3fccac101` | 20.879 | 100,916 | 110,192 |
| 16 | provided | `t16-calibration_provided_6` | `a-c2f55e2a8fe0` | 36.686 | 248,841 | 897,579 |
| 17 | baseline | `t17-calibration_baseline_5` | `a-0f7d4a7e841d` | 30.093 | 83,087 | 91,837 |
| 18 | baseline | `t18-calibration_baseline_6` | `a-4372d20f2046` | 25.042 | 82,759 | 89,032 |

### Source references

For each attempt, `manifest-<attempt>.json` is the captured artifact manifest
under the private experiment; `objects/<hex>` holds the transcript bytes.
Full hashes below allow the custodian to identify the exact retained evidence.

| Attempt | Manifest SHA-256 | Transcript SHA-256 |
|---|---|---|
| `a-6a665d9ffdb3` | `sha256:a3257dd7dfe8159597e42c877c100ef6bd2954ed34dab05edb9a8ea3d5425eca` | `sha256:521a1d97be220d014b535f0ccd22996f4aaa00c3b4af551c9b775974b07dc2e9` |
| `a-4804389ad794` | `sha256:c61d0782257ddf5fd479f00d3e07316fbb22f81a88f43314a937b5fa49372654` | `sha256:faed89192361481615eabb3fcc9f497a736713ce4f4cad4005fdcf9817553a1b` |
| `a-e59219401131` | `sha256:05fe7b44c185f95046b68f228f934e5c352b5c983555a555f8deaa58aa739b9f` | `sha256:a1854bae0d505f16f314bc89aa334f019c20f26852872cd40eafdf4c43f39b5a` |
| `a-c25dbeda42f9` | `sha256:e7ca31fe2cd66efa33c26451742d4f77bd0e885c95ba3155ea6a34fe31394230` | `sha256:e33877abe87b9136d8e1bdc1a7da27df64955b2ccfeef8aedfaa5e6a534fe034` |
| `a-8ac39d185d9b` | `sha256:0dd101fd8f70fe52c58ee2a543c7ed73a00dd250c91abf39a1d4efc9698e3e2b` | `sha256:8b3aafa10324c55a005735f769d2906e6568c161b94bdddea9da930b731053d6` |
| `a-cd2c7a7de61f` | `sha256:b3827783de49e3e7849d2edbfb9eb384c1130010dac512aa74c3d0809f420b52` | `sha256:c8565da1e0ad088f32bc74acb5e4a1663ea4eb4b4879d7fd4efd217979e99634` |
| `a-9910332511de` | `sha256:6b6e27be6ebb5e103b435b087ada4cdc9432d14a2cfe1256287243d29bef72fb` | `sha256:f45e0b0b74400eba55a566d1768be9bf84afce903d3346d4564b8f0ca232577b` |
| `a-33e3a074fb73` | `sha256:3ee136172c9bf1de3e3a7a2ea3d63835c198e0d6a2800c7c0c015acbc2ed25e0` | `sha256:f27cd8adaed377c168238fa014b462646f3e5198e22c5a49d594727680fc3a24` |
| `a-1da9c71eb6b5` | `sha256:ac283d82bfe2965fb90343882306e117ae42da5d468c9f8f8fbcbdedcdeae8f2` | `sha256:11051cb30001a0be53353b9eb45e39e17b70ac9fe92cec6cbf7c27a67e542f36` |
| `a-9f97c35241ab` | `sha256:06d9f1a1e13e8903d67e9ebd9c6aa70843516a032629e8b4d0352b302806d91c` | `sha256:20d4c66be4b403af69be6772fdc0c9ccb5d4fa004a99cc3eb63cd338662e3f3f` |
| `a-95ca2d8b76d9` | `sha256:0d6b383cd12f7a5fa6a7c0f0b4839dd85053dc4258899423122fc5c114ae829f` | `sha256:b377a837fd8da1dee84fcfe93313dfb662433e91dcda1a6d71d7113cebe16b40` |
| `a-6080c0c0cbdc` | `sha256:18ee1242f89ff79b255eb0ff2c13e2fc2e8b6c75a61fe257a4e201a0f5ba9b5e` | `sha256:7c4359ae6ffe49a4ca3a3c42ef6eaa9689b629ba1eb2024937caecdd027d558c` |
| `a-c5139d389d36` | `sha256:52ed070d86fb7e5bfc396ec17e93bffae469e5dd47f7f258dde8c9f26b62cfd9` | `sha256:fd5ad6107d94c05bff2d04fde7cabdb0fbb7be3237f8396c7469e58e2079b8da` |
| `a-296bc1df27ca` | `sha256:ea31a543289b5be14ed412792ff8852e373b868b1a81c7ef65ecda8f24142442` | `sha256:cf677da2568b19bf9e89412b02f31235fa9ccb2b3f59d41919cd1dc5474daa04` |
| `a-b5e3fccac101` | `sha256:b6601d8c3e4fc77db563f591b4229153a6c5e512ff96e80671b002d1f41ca6b2` | `sha256:011debbacf2ea8a2087da6fe38838a57fa9ab8c987ca01fe4b910fe11b7811b9` |
| `a-c2f55e2a8fe0` | `sha256:9fa4355e8943fbff3659aa84fae796b2a1bf913f9afc8b42de1c66e99c3b0785` | `sha256:7e641d9ab806fe36769aaa2365d31b8469184d24737a8c6e3592b13982d1923f` |
| `a-0f7d4a7e841d` | `sha256:d7998cdecafe647132be0be528dd63d648c88f96c334cb160e0753526ecec128` | `sha256:f6750a6f9632ee90f2ff2fb6fe1ddfb33e008096a138d114ba9cc56b4761dd8e` |
| `a-4372d20f2046` | `sha256:6121d9ca85d1306226d35e60147aee3ea9151ddb6395054a0d502a4736405d66` | `sha256:e5e03ac33ee73522ed6d84ddb8567cf591a35df6d48792f509e166c17bcaa1c5` |

## Preparation checks and review

`make verify` passed on the frozen runtime/preparation: 6907 tests passed,
5 expected skips, 6912 collected identities matched the JUnit report. Ruff,
mypy (316 source files), selftest and general/type/privacy/security/git/
population negative controls passed; changelog and README drift passed.
The skips are two diagnosed frontmatter cases, an explicitly opt-in timeout
control, and two cleanup tests reserved for the separately locked real-Docker
runner. Later comment-only declaration wording was separately reviewed by root.

Ten committed preflight controls passed. Historical grader certification refused
five broken graders and held 13 validity controls. Missing approval refused;
the actual frozen launch-ready check passed after approval. The independent
review used measured `codex/gpt-6-astra` against `codex/gpt-6.1-sol`, two passes,
full file scope, blocked network probe with an outside positive control, and no
repository-local credential configuration. All three medium findings were
fixed: complete passing controller scratch input before byte mutation; fresh
preflight import cache; fresh qualification-subprocess cache. Actual pre-review
code failed each targeted check and fixed code passed. No third review ran.
Receipt: `docs/measurements/counter-model/2026-10-24T215806Z-issue-557.json`.

## #28 hand-off

One exact retained provided-arm artifact can seed a bounded development replay
of this historical grader distinction, with source identity preserved and an
independent known-good counterpart. It must explicitly retain the ambiguity,
avoid labeling the case a causal CPP defect, and keep development/held-out
separation. That concrete fixture needs its own reviewed gate. PR #161 already
delivered #28's identity-comparison half; it is not duplicated here. No added
trial is authorized or needed to force a failure.
