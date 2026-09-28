"""A fake `pip`, importable as a module (`python -m pip ...`), so
`probe.py`'s mode-selection can be exercised even though real pip and a real
build backend are absent everywhere this repository currently runs (see
README.md). Never a real package manager: implements only the two calls
`probe.py._pip_available`/`_real_pip_install` actually make. See
`check_real_pip_mode.py` for how this is used."""
