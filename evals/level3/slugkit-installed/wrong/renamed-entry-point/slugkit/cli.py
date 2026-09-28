"""Known-bad (c): the entry function was renamed from `main` to `run` here,
but `pyproject.toml`'s `[project.scripts]` target (`slugkit.cli:main`) was
never updated - the installed console command's target no longer exists."""

import sys

from .core import slugify


def run():
    title = sys.argv[1] if len(sys.argv) > 1 else ""
    print(slugify(title))


if __name__ == "__main__":
    run()
