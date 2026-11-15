# Lanes demonstrated: #741

<!-- lanes-demonstrated run=0e25040917c04ad9a2b9707289246259 plan=16877808b55e355ac4e7a4a9a66e582f27f1fd2ede8181080d93009f88cfbad2 -->

| Lane | Result | Evidence |
|---|---|---|
| Run placement | passed | host make verify targeted set on 097b3f5: ruff, bare mypy, leak-check, selftest 39/39, 730 tests in `tests/test_decay.py`, `tests/test_inspect.py` and neighbours. woodpecker ci not run yet (the PR opens after #744 merges); real-docker runner vm not applicable |
| Subject collection | passed | `docs/measurements/inspect/2026-11-14-cpp-and-mattpocock.md` "Re-run after #741": cpp at pinned shas d5ef0a66 and 93ae8540 and mattpocock-skills 5863806, plus synthetic `tests/test_decay.py::test_741_*`; tokeniser parity on 17,694 corpus spans |
| skillc distribution | passed | source checkout: the targeted set above. built wheel in a clean venv not run yet (PR CI clean-install) |
| Python version | passed | 3.12 tested: the targeted set above. >=3.11 declared not run for this change |
