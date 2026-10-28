- **Gate clean wheel installations** (#72). Run the built-wheel check and its
  installed-rule, missing-controls and same-exit/different-findings controls in
  local verification and CI. Propagate structured comparison failure instead of
  printing success after its Python process fails.
