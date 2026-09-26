"""skillc - skills are the new code. Code doesn't ship uncompiled."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

#: `pyproject.toml`'s `version` is the ONE source of truth (#73). This reads the
#: package's installed distribution metadata rather than carrying a second
#: literal that could silently drift from it - the exact defect #73 exists to
#: close (this file and pyproject.toml disagreed for the whole evaluation-
#: facility milestone before it was fixed). An editable install (`uv sync`,
#: `pip install -e .`) still has real dist-info, so this works in dev too.
try:
    __version__ = _installed_version("skillc")
except PackageNotFoundError:  # pragma: no cover - only when unbuilt and uninstalled
    __version__ = "0+unknown"
