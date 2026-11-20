<!-- flow-run n=1 id=09b683181b2a424dbebe83c2deeff7de -->
## Run 1 - issue #730 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #730
- Read at:      2026-11-19T11:31:19Z
- updatedAt:    2026-11-14T21:18:13Z   (context only - moves on comments and labels)
- Body digest:  4d29353156cf52e1e2f34ede915bfc4164ff65be4df94f5b1666f354f643e583   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1964 of 1964 (cap 16384)

### Body as read
## What is wrong

`skillc/leak.py` `_host_encoded_accounts()` (#729) treats a non-empty `pwd.getpwall()` listing as the **complete** set of host accounts. NSS/SSSD can disable enumeration of directory accounts while still allowing lookup by name. Then `getpwall()` returns only local accounts such as `root`, and leaves out a real directory account like `user.operator` that `getpwnam()` resolves.

`_encoded_exempt("user")` then sees no account the placeholder prefixes and exempts the encoded placeholder home. That silences the encoded home path of that real `user.operator` account (the `-home-` form followed by the account's dashed name). Codex reproduced this in memory with an account resolvable by `getpwnam()` but absent from `getpwall()`.

## Why it matters

On a directory-backed host, a real account whose encoded name starts with `user-`, `u-` or `proof-` can pass leak-check unreported. That's narrow, since the account name has to begin with one of the three placeholders, but it is a silent miss in a gate that lets commits through.

## Fix (design call)

Grant the encoded exemption only where the enumeration can be shown complete; otherwise withhold it, which is the strict behaviour. Possible signals:
- the NSS `passwd` source is `files` only;
- `getpwnam()` confirms every encoded candidate actually seen in the scanned text.

The second is likely the better shape: for each encoded match, try the dotted, dashed and underscored de-encodings of the full matched token with `getpwnam()`, and fire if any of them resolves.

Also consider covering the **current** account by uid, so the scanning account's own encoded home is never exempt.

Add a regression case: a non-empty local listing that omits a resolvable colliding account must still fire. Show it failing on the pre-fix code.

Found by the counter-model review (Codex, codex/gpt-6.1-sol, pass 3) of #729's branch. Deferred under the owner's ruling (no fourth pass). Refs #729, #470.


<!-- end of body -->
