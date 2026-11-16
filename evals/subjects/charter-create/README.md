# charter-create controls (#778)

The planted collection `collection/` holds one skill, `skills/demo`. Its committed
`evidence.json` is `skillc charter evidence collection skills/demo` with no repository
reader; `tests/test_charter_create.py` regenerates it and fails if it drifts.

`answers.json` is a complete set of owner answers: every suggestion answered, an
intent the owner approves, one must-always, one must-never with its shortcut, and one
authority clause with its shortcut. The tests derive every refusal case from it by
removing or changing one field, so each control differs from the good case in one place.
