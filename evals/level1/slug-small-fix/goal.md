# Task: fix the slug trailing hyphen

`slugify("Hello, World!")` returns `"hello-world-"`. It should return `"hello-world"`.

Fix `slugify` in `src/slugify.py` so that, for any title string:

- **R1** - the slug is lowercase.
- **R2** - every run of one or more characters other than ASCII `a`-`z` and `0`-`9`
  becomes a single hyphen.
- **R3** - the slug has no leading or trailing hyphen. A title with no letters or
  digits gives the empty string.
- **R4** - `slugify(title)` stays a function named `slugify` in `src/slugify.py`
  that takes one string and returns a string, using only the Python standard library.

You may add or change other files if that helps you. Then, in your final message,
state what you changed.
