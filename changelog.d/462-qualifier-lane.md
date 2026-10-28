- **Run trusted artifact qualification without sibling-worker contention**
  (#462). Include `test_change_with_regression_568.py` in the isolated pytest
  phase, with committed lane-placement and missing/dropped/duplicate qualifier
  identity controls. Preserve every frozen qualification byte, the five-second
  probe cap, the 450-second whole budget, and the explicit 0.3-second timeout red.
