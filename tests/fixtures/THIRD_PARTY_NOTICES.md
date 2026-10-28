# Third-party notices for frozen CPP snapshots

The following vendored snapshots contain code from
https://github.com/cooneycw/claude-power-pack, copyright cooneycw, under the
upstream MIT license reproduced below. These notices accompany the copies in
this repository. Keep this notice with these snapshots when redistributing them.
The other `profile-cpp-*` snapshots carry their own in-tree `LICENSE` files.

| Snapshot directory (relative to this file) | Upstream revision |
|---|---|
| `profile-cpp-codex-cicd-86641e8` | `86641e817711d8a7746270745a5dfa7cacf04b0c` |
| `profile-cpp-codex-flow-check-86641e8` | `86641e817711d8a7746270745a5dfa7cacf04b0c` |
| `profile-cpp-codex-flow-check-ea6dbfa` | `ea6dbfa45f9308ee6ba60f032d8e7031bd6938a1` |

Both revisions contain byte-identical upstream `LICENSE` files, reproduced
verbatim once below, including the upstream scope and third-party-service notes.
SHA-256: `c6c2630fa5d672358d322509c5c073f87fa89f59157a93fe0b4067edd0260c60`.

This file deliberately lives outside each frozen snapshot directory: adding a
file inside one changes its whole-tree `snapshot:sha256` identity. It changes no
snapshot bytes or membership, profile inventory, installed surface, historical
evidence or experiment approval. This source-notice repair addresses only the
license-notice item of #553; the other profile-walker limits remain open.

```text
MIT License

Copyright (c) 2025 cooneycw

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## Scope

This license applies to:
- All scripts in the `scripts/` directory
- All commands in the `.claude/commands/` directory
- The MCP Second Opinion server code in `mcp-second-opinion/`
- Configuration files and templates

## Community Content

The best practices documentation (CLAUDE_CODE_BEST_PRACTICES*.md) is compiled
from public posts on r/ClaudeCode. Original authors are credited in the
Acknowledgments section of README.md. This content is provided for educational
purposes with attribution to the community contributors.

## Third-Party Services

This repository includes tools that integrate with third-party services:
- Google Gemini API (subject to Google AI Terms of Service)
- OpenAI API (subject to OpenAI Terms of Use)
- GitHub API (subject to GitHub Terms of Service)
- Claude Code (subject to Anthropic Commercial Terms of Service)

Users are responsible for compliance with each service's terms.
```
