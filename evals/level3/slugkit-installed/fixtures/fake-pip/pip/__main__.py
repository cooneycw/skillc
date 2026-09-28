"""A fake pip, importable as a module (`python -m pip ...`) so it satisfies
probe.py's `_pip_available` check without a real network or a real backend.
Only implements exactly what probe.py calls: `--version` and
`install --no-index --no-build-isolation --target DIR SRC`."""

import shutil
import sys
import tomllib
from pathlib import Path


def main():
    argv = sys.argv[1:]
    if argv == ["--version"]:
        print("fake-pip 0.0.0 (mode-selection test double)")
        return 0
    if argv[:1] == ["install"]:
        target_idx = argv.index("--target")
        target_dir = Path(argv[target_idx + 1])
        src_dir = Path(argv[-1])
        with (src_dir / "pyproject.toml").open("rb") as handle:
            data = tomllib.load(handle)
        packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
        for package in packages:
            shutil.copytree(src_dir / package, target_dir / package, dirs_exist_ok=True)
        return 0
    print(f"fake-pip: unimplemented argv {argv!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
