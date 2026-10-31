# Wave qualification floor controls

Every unrelated declared real-Docker file passes in all five reports. The
physical wave file alone changes: five passes, absent, five skips, one failure,
or one error. `cases.json` records the required verdict. Removing only the
wave entry from the declared floor makes each bad report falsely succeed.

`tests/test_real_docker_verdict.py` consumes these committed inputs. The five
new cases failed before floor registration and pass with the entry present.
The existing floor tests also include a passing wave prerequisite so another
missing file cannot mask the behavior each old case is meant to discriminate.
