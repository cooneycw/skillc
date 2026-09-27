#!/usr/bin/env node
// Verify codex-code-mode-host lands beside the REAL native codex executable
// (issue #10 lesson A2: installing only 'codex' silently degrades to fluent
// prose, zero tool calls, exit 0, and a still-green 'codex doctor').
//
// A build-time check, and a Codex code-review finding on issue #78 that this
// script exists to fix: searching for the sidecar beside the npm package's
// launcher script (bin/codex.js) is the WRONG directory. codex.js resolves
// the real native binary through its own platform package
// (`@openai/codex-<platform>-<arch>`) and a vendor/<target-triple>/bin/
// directory - confirmed by extracting the actual pinned 0.157.1 tarballs
// (bin/codex.js's own findCodexExecutable(), and codex-linux-x64's real
// contents: vendor/x86_64-unknown-linux-musl/bin/{codex,codex-code-mode-host}
// side by side).
//
// A SECOND, later bug in this same script (found on a real operator build,
// Dockerfile:80): the Dockerfile COPYs this file to /tmp and runs it from
// there, so a bare `require.resolve("@openai/codex-linux-x64/package.json")`
// walked up from /tmp's own ancestry (/tmp/node_modules, /node_modules) -
// nowhere near where npm actually put anything. bin/codex.js's identical
// call never hits this, because codex.js itself LIVES inside the installed
// package tree, and npm nests an optional platform dependency under its
// OWNER's own node_modules/ (<global root>/@openai/codex/node_modules/
// @openai/codex-linux-x64/), never beside it at the shared global root.
// #84's own test exercised only the wrong shape: NODE_PATH pointed straight
// at a flat fixture, which the real Dockerfile invocation never sets and
// which no real npm install ever produces - so the test passed while the
// real build failed with "Cannot find module
// '@openai/codex-linux-x64/package.json'", confirmed by hand-building the
// real nested layout from the actual published 0.157.1 tarballs and running
// this script, unmodified, from a directory with no relation to it.
//
// The fix mirrors codex.js's OWN resolution chain instead of a bare
// require.resolve from wherever this script happens to be: find
// @openai/codex itself from the npm global root (asked via `npm root -g`,
// exactly what a real `npm install -g` used), then createRequire scoped to
// THAT package's own directory to resolve its platform optional dependency
// - the same two-hop path codex.js's own findCodexExecutable() takes.
"use strict";

const { existsSync, statSync } = require("fs");
const { execFileSync } = require("child_process");
const path = require("path");
const { createRequire } = require("module");

const PLATFORM_PACKAGE_BY_TARGET = {
  "x86_64-unknown-linux-musl": "@openai/codex-linux-x64",
  "aarch64-unknown-linux-musl": "@openai/codex-linux-arm64",
};

const TARGET_TRIPLE_BY_ARCH = {
  x64: "x86_64-unknown-linux-musl",
  arm64: "aarch64-unknown-linux-musl",
};

function fail(message) {
  console.error("verify_codex_sidecar: " + message);
  process.exit(1);
}

const targetTriple = TARGET_TRIPLE_BY_ARCH[process.arch];
if (!targetTriple) {
  fail("unsupported architecture: " + process.arch);
}

const platformPackage = PLATFORM_PACKAGE_BY_TARGET[targetTriple];

// CODEX_NPM_ROOT is a test-only override (never set in the Dockerfile): it
// lets a test point this at a fixture's fake global root without spawning a
// real npm, while the real invocation always asks npm itself where its
// global root actually is - never a guessed or hardcoded prefix path.
function npmGlobalRoot() {
  if (process.env.CODEX_NPM_ROOT) {
    return process.env.CODEX_NPM_ROOT;
  }
  try {
    return execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
  } catch (err) {
    fail("could not determine the npm global root (`npm root -g` failed: " + err.message + ")");
  }
}

// A direct path join, never require.resolve() here (a Codex code-review
// finding on this same PR): `require.resolve(id, { paths })` does not
// confine the search to the given directory - it treats each path as a
// STARTING point and then walks UP through every ancestor's own
// node_modules, exactly like ordinary resolution from a file there. `npm
// root -g` already gives the exact directory npm would use, so there is
// nothing to search for - an unrelated @openai/codex sitting in some
// ancestor directory (a stray dev dependency, a different global prefix
// layered on PATH) must never let this check pass for the WRONG
// installation. Confirmed: with an empty declared global root but a real
// @openai/codex two directories up, require.resolve(..., { paths }) silently
// resolved to the ancestor copy instead of refusing.
const npmRoot = npmGlobalRoot();
const codexPackageJsonPath = path.join(npmRoot, "@openai", "codex", "package.json");
if (!existsSync(codexPackageJsonPath)) {
  fail("cannot resolve @openai/codex from the npm global root " + npmRoot);
}

const codexRequire = createRequire(codexPackageJsonPath);

let packageJsonPath;
try {
  packageJsonPath = codexRequire.resolve(platformPackage + "/package.json");
} catch (err) {
  fail("cannot resolve " + platformPackage + " (is @openai/codex installed? " + err.message + ")");
}

const vendorBin = path.join(path.dirname(packageJsonPath), "vendor", targetTriple, "bin");
const nativeCodex = path.join(vendorBin, "codex");
const sidecar = path.join(vendorBin, "codex-code-mode-host");

function requireExecutableFile(filePath, label) {
  if (!existsSync(filePath)) {
    fail(label + " is missing at " + filePath);
  }
  const st = statSync(filePath);
  if (!st.isFile()) {
    fail(label + " at " + filePath + " is not a regular file (found a directory or other special file)");
  }
  if ((st.mode & 0o111) === 0) {
    fail(label + " at " + filePath + " is not executable");
  }
}

requireExecutableFile(nativeCodex, "native codex executable");
requireExecutableFile(sidecar, "codex-code-mode-host");

console.log("verify_codex_sidecar: ok - " + sidecar);
