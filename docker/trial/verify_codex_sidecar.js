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
// side by side). This script replicates that SAME resolution via Node's own
// module system, rather than a shell heuristic that can silently accept a
// same-named directory or non-executable file in the wrong place.
"use strict";

const { existsSync, statSync } = require("fs");
const path = require("path");

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

let packageJsonPath;
try {
  packageJsonPath = require.resolve(platformPackage + "/package.json");
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
