<!-- flow-run n=1 id=60120f9e47bb4b09a4b462c9667b96da -->
## Run 1 - issue #505 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #505
- Read at:      2026-10-21T05:29:13Z
- updatedAt:    2026-10-21T05:28:07Z   (context only - moves on comments and labels)
- Body digest:  804342a0c768a71bf87ab1d6432f91e45ef7debebfeffc25b53533f584aeb118   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2261 of 2261 (cap 16384)

### Body as read
## Installed subject helpers are not executable in live trials (mode 0600)

**Severity:** this affects the validity of every live Level-3 measurement that installs a profile treatment (#434's campaigns; possibly #287). It changes what the agent can do, so it changes what is measured.

### What happens
`agent_trial._make_before_execute` delivers every `extra_home_files` entry, which is how a profile treatment installs the subject's skills and helper scripts, through `DockerBackend.deliver_home_file`. It never passes `mode`, so every file lands at the default **0600** (`skillc/agent_trial.py:961`, `skillc/docker_backend.py:1651`). That includes CPP's `~/.claude/scripts/flow-*.sh`, which the subject expects to run directly.

### Evidence (owner-approved #434 revision-5 campaign `20261021T050644Z-25a382`, private)
- 9 of 10 attempts hit `Permission denied` on an installed helper. The agent's own `ls -l` shows `-rw------- ... /home/candidate/.claude/scripts/flow-start-resolve.sh`.
- Most attempts worked around it by running the helpers through `bash` or `python3`.
- One TWIN attempt (`a-466914b6110e`) ran `flow-start-resolve.sh` directly, got exit 126, and stopped at Step 1, exactly as flow:auto's template says ("Stop immediately if any step fails"). It was graded FAIL for stating no verdict.
- The revision-4 campaign's store (`20261020T195431Z-fab3ce`) also holds `Permission denied` outputs. This predates grader revision 5.

### Why it matters
The measured behaviour is partly "does the agent route around a broken install" rather than "does flow:auto handle a fixed issue". One FAIL in the revision-5 campaign is this environment, not the agent's judgment and not the grader.

### What a fix needs
- Deliver installed files with their declared mode. A profile closure records each file's content; it needs the executable bit too, or a rule that `scripts/` helpers are 0755.
- A red: a live-path test showing an installed helper is executable in the attempt container. Its control: the same file at 0600 is not.
- Any future campaign's declaration names the fix's revision; this changes the install, so the approved declarations are spent.

Found by skillc-worker-A (wave skillc-400) verifying the #434 revision-5 campaign.

Refs #434 #499

