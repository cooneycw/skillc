#!/usr/bin/env bash
# Same exit codes, different structured findings: the clean-install gate must fail.
# This committed case changes only the packaged JSON immediately before the final
# Python comparison. It exercises the branch the installed-rule sabotage misses.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
real_python="$(command -v python3)"
mkdir "$scratch/bin"
cat > "$scratch/bin/python3" <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
case "${2:-}" in
  */baseline-bad.json)
    "$CLEAN_INSTALL_REAL_PYTHON" - "$3" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text())
assert data["findings"], "the bad-fixture population must not be empty"
data["findings"][0]["rule"] = "injected-packaging-mismatch"
path.write_text(json.dumps(data))
PY
    ;;
esac
exec "$CLEAN_INSTALL_REAL_PYTHON" "$@"
WRAPPER
chmod +x "$scratch/bin/python3"
set +e
CLEAN_INSTALL_CONTROL= CLEAN_INSTALL_REAL_PYTHON="$real_python" PATH="$scratch/bin:$PATH" \
    bash "$root/ci/clean-install-check.sh" > "$scratch/output" 2>&1
code=$?
set -e
cat "$scratch/output"
if ! grep -Fq "packaged found ['injected-packaging-mismatch']" "$scratch/output"; then
    echo 'clean-install-comparison-control: FAIL - sabotage did not reach the structured comparison' >&2
    exit 1
fi
if [[ $code -ne 1 ]]; then
    echo "clean-install-comparison-control: FAIL - mismatched findings exited $code, expected 1" >&2
    exit 1
fi
if grep -Fq 'ok - the packaged checker matches the source baseline on both fixtures' "$scratch/output"; then
    echo 'clean-install-comparison-control: FAIL - failed comparison printed success' >&2
    exit 1
fi
echo 'clean-install-comparison-control: ok - same-exit mismatched findings refused (exit 1)'
