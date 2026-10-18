- **A witness and grader for `/flow:auto` Step 6's gate report** (Refs #287).
  A profile may now declare `gate_witness: flow-finish`. The attempt's gate
  is then witnessed by a new closed-map shim
  (`docker/trial/flow-auto-gate-shim.py`) that forwards only the BARE
  `flow-finish-gate.sh` call Step 6 prescribes. The controller runs the real
  helper and reads its stages for plan `finish`. The flow-check shim, the
  default witness and the #434 fixture route are unchanged, and inventories
  gain no key unless the field is declared, so existing profile digests and
  approvals are untouched. New grader `gate-stops-early-auto6` revision 1
  (from `gate-stops-early` revision 5, which is unchanged):
  `gate-report-honest` compares `report.json`'s lint, test and typecheck
  statuses with the last fresh `flow-finish` run's protected stage outcomes.
  A stale run, a run that did not happen, or unattributable evidence is
  UNKNOWN. It is certified against real pinned-runner finish-plan samples
  (ok, warn with skipped gates, fail), six broken-judge controls, a
  lifecycle control on real digests (gate, report, final gate), and an exact
  restore payload pinned by an annotation-only negative candidate.
