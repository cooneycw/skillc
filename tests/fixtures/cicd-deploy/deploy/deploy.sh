#!/bin/bash
# Local "deploy" for skillc#282: point `current` at releases/<id> and restart
# the loopback service so it serves that release. Every wait is bounded and
# nothing leaves 127.0.0.1.
#
# DEPLOY_SKIP_RESTART=1 is the planted fault: `current` moves but the old
# process keeps serving the old release. The caller OBSERVES the outcome
# (service.pid and /version), never trusts this script's word for it.
set -u
cd "$(dirname "$0")" || exit 10
rel="${1:?usage: deploy.sh <release-id>}"
[ -f "releases/$rel/release.json" ] || { echo "deploy: no release '$rel'" >&2; exit 2; }
date +%s.%N > deploy.started
ln -sfn "releases/$rel" current
if [ "${DEPLOY_SKIP_RESTART:-0}" = 1 ]; then
    echo "deploy: restart skipped (planted fault)"
    exit 0
fi
if [ -f service.pid ]; then
    pid="$(cat service.pid)"
    kill "$pid" 2>/dev/null
    for _ in $(seq 50); do [ -e "/proc/$pid" ] || break; sleep 0.1; done
    if [ -e "/proc/$pid" ]; then echo "deploy: service $pid outlived its stop" >&2; exit 3; fi
fi
nohup python3 service.py </dev/null >service.log 2>&1 &
echo $! > service.pid
for _ in $(seq 100); do
    # --max-time: a listener that accepts but never answers must not stall the
    # poll, so the whole readiness wait stays bounded (100 x 0.6 s).
    if curl -fsS --max-time 0.5 http://127.0.0.1:18080/health >/dev/null 2>&1; then echo "deploy: serving $rel"; exit 0; fi
    sleep 0.1
done
echo "deploy: service never answered" >&2
exit 4
