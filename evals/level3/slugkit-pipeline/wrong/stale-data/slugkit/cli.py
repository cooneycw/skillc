"""The console-script entry point (`[project.scripts]`): `slugify_installed TITLE`."""

import sys

from .core import slugify


def main():
    title = sys.argv[1] if len(sys.argv) > 1 else ""
    print(slugify(title))


if __name__ == "__main__":
    main()
