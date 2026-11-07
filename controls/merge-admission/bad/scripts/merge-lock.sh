#!/usr/bin/env bash
# An inner acquire: waits on the merger that is waiting on this pipeline.
set -euo pipefail
kyle-lock acquire main-merge --request-key ci-inner --purpose "ci holds main-merge"
echo merged-under-ci-lock
