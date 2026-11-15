# Lanes demonstrated: #745

<!-- lanes-demonstrated run=d66562df541646c7b8df1d204e3fe218 plan=bc141d7cec94f8002986583cf748e1ea89887f2ffd3d71a1d77e0b8e0280856e -->

| Lane | Result | Evidence |
|---|---|---|
| Run placement | not run | host make verify targeted set passed (ruff, bare mypy, leak-check, selftest, targeted pytest); woodpecker ci NOT RUN until this PR's pipeline (silent period, and stacked behind #748) |
| Subject collection | passed | `docs/measurements/inspect/2026-11-14-cpp-and-mattpocock.md` "Re-run after #745": cpp at pinned shas d5ef0a66 and 93ae8540, mattpocock-skills 5863806; synthetic `tests/test_decay.py::test_745_*` |
| skillc distribution | not run | source checkout passed (the targeted set); built wheel in a clean venv NOT RUN until PR CI clean-install |
| Python version | passed | 3.12 tested: the targeted set |
