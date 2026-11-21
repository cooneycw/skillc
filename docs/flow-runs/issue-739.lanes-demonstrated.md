<!-- lanes-demonstrated run=bdb424be606e41bc905e5e21fe0b3b4d plan=80b7a02be9fc5b2cbf4dc36af1371ac3c8658b09d8b4041848126c6585ea19da -->

| Lane | Result | Test or observation |
|---|---|---|
| Static-check target | passed | portable: `skillc selftest` 48/48, contract-shape red on 10 bad (incl. new `controls/contract-shape/bad/dash-spacing`), green on 2 good; claude-code not exercised separately (contract rules are target-independent) |
| Subject collection | passed | synthetic: `tests/test_contracts.py::test_a_mis_aligned_wide_dash_list_item_is_a_shape_error`, `::test_an_unreadable_directory_with_no_contract_found_is_not_none_declared`, and the PyYAML differentials in `tests/test_frontmatter_subset.py` |
