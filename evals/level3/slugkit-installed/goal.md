# Task: fix slugkit's trailing hyphen, so it works installed too

`slugify("Hello, World!")` returns `"hello-world-"`. It should return
`"hello-world"`.

Fix `slugify` in `slugkit/core.py` so that, for any title string, a run of
one or more characters other than ASCII `a`-`z` and `0`-`9` becomes a single
hyphen, the slug is lowercase, and it has no leading or trailing hyphen -
for example, `slugify("Rock & Roll!")` should return `"rock-and-roll"`
(`&` becomes the word "and", via the replacements table below).

This package also ships a symbol replacements table at
`slugkit/data/replacements.json` (e.g. `"&"` -> `"and"`), which `slugify`
must keep reading from that SHIPPED file - not a hardcoded constant - so a
future locale/translation swap needs no code change.

**Your fix is graded two ways, separately:**

1. **The visible unit test** (`tests/test_core.py`) run directly against
   your source tree.
2. **The installed path**: this package's `pyproject.toml` declares a
   console command (`[project.scripts]`); your fix is graded again by
   copying the package directories and data files your `pyproject.toml`
   declares into an isolated install, then running that console command -
   not by re-running the unit test a second time. A fix that only passes
   the unit test, but breaks when actually packaged and invoked through its
   real entry point, does not pass this task.

You may add or change other files if that helps you. Then, in your final
message, state what you changed.
