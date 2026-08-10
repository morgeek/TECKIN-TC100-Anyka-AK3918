#!/usr/bin/env node
// Renders www/index.html in real Chromium against a stubbed cgi-bin/state.cgi
// and asserts the firmware-version chip / update-notifier badge behave
// correctly for each combination of {current_version, update_available}.
//
// Recreated 2026-08-10 after the original Wave 1 branch (and its test suite)
// was lost when the sandbox that authored it was reclaimed. See
// claude/status-2026-07-28.md in the project for that history.

import { chromium } from "playwright";
import http from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const wwwDir = path.join(rootDir, "www");

let pass = 0;
let fail = 0;
function ok(cond, msg) {
  if (cond) {
    pass++;
  } else {
    fail++;
    console.error("FAIL: " + msg);
  }
}

// Strip HTML comments before scanning for the old hardcoded-version string,
// mirroring the harness-bug fix from the original run: a naive grep matches
// comments that merely *document* the old bug, producing a false pass.
function stripHtmlComments(html) {
  return html.replace(/<!--[\s\S]*?-->/g, "");
}

async function assertNoHardcodedVersion() {
  const html = await readFile(path.join(wwwDir, "index.html"), "utf8");
  const stripped = stripHtmlComments(html);
  ok(!/v1\.1\.0-ELITE/.test(stripped), "index.html must not contain the old hardcoded v1.1.0-ELITE string outside comments");
  // Self-test: a comment-only occurrence must NOT trip the check (the stripper isn't over-eager).
  const commentOnly = "<!-- used to say v1.1.0-ELITE here -->";
  ok(!/v1\.1\.0-ELITE/.test(stripHtmlComments(commentOnly)), "comment stripper self-test");
}

function startServer(statuslineFactory) {
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://localhost");
    if (url.pathname === "/cgi-bin/state.cgi" && url.searchParams.get("cmd") === "statusline") {
      const body = JSON.stringify(statuslineFactory());
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(body);
      return;
    }
    let filePath = path.join(wwwDir, url.pathname === "/" ? "index.html" : url.pathname);
    try {
      const data = await readFile(filePath);
      res.writeHead(200);
      res.end(data);
    } catch {
      res.writeHead(404);
      res.end("not found");
    }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

async function withPage(statuslineFactory, fn) {
  const server = await startServer(statuslineFactory);
  const { port } = server.address();
  // Prefer the sandbox's preinstalled Chromium; fall back to Playwright's own
  // download (e.g. in CI, where `npx playwright install chromium` provides it).
  const fs = await import("node:fs");
  const SANDBOX_CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
  const launchOpts = { args: ["--no-sandbox"] };
  if (fs.existsSync(SANDBOX_CHROME)) { launchOpts.executablePath = SANDBOX_CHROME; }
  const browser = await chromium.launch(launchOpts);
  try {
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${port}/index.html`);
    // Wait for at least one statusline poll to complete and update the chip.
    await page.waitForFunction(() => {
      const el = document.getElementById("fw_version");
      return el && el.textContent && el.textContent !== "version n/a";
    }, { timeout: 5000 }).catch(() => {});
    await fn(page);
  } finally {
    await browser.close();
    server.close();
  }
}

async function testCurrentVersionShown() {
  await withPage(
    () => ({ sysusage: "CPU: 5% RAM: 1/2 kB", update_available: 0, update_latest_version: "n/a", current_version: "v1.3.0" }),
    async (page) => {
      const text = await page.$eval("#fw_version", (el) => el.textContent.trim());
      ok(text === "v1.3.0", `fw_version chip should show v1.3.0, got "${text}"`);
      const classes = await page.$eval("#fw_version", (el) => el.className);
      ok(!classes.includes("fw-outdated"), "chip must not be marked outdated when update_available=0");
      const badgeActive = await page.$eval("#update_notifier", (el) => el.classList.contains("is-active"));
      ok(!badgeActive, "update badge must be inactive when no update is available");
    }
  );
}

async function testUpdateAvailableAmber() {
  await withPage(
    () => ({ sysusage: "CPU: 5% RAM: 1/2 kB", update_available: 1, update_latest_version: "v1.4.0", current_version: "v1.3.0" }),
    async (page) => {
      const classes = await page.$eval("#fw_version", (el) => el.className);
      ok(classes.includes("fw-outdated"), "chip must be marked outdated when update_available=1");
      const badgeActive = await page.$eval("#update_notifier", (el) => el.classList.contains("is-active"));
      ok(badgeActive, "update badge must be active when an update is available");
      const title = await page.$eval("#update_notifier", (el) => el.title);
      ok(title.includes("v1.4.0") && title.includes("v1.3.0"), `badge title should mention both versions, got "${title}"`);
    }
  );
}

async function testMissingVersionHandled() {
  // D: state.cgi answers but /mnt/VERSION was unreadable -> "n/a". Must not render literal "undefined".
  await withPage(
    () => ({ sysusage: "CPU: 5% RAM: 1/2 kB", update_available: 0, update_latest_version: "n/a", current_version: "n/a" }),
    async (page) => {
      const text = await page.$eval("#fw_version", (el) => el.textContent.trim());
      ok(text === "version n/a", `fw_version chip should show the n/a fallback, got "${text}"`);
      ok(!text.includes("undefined"), "chip must never render the literal string 'undefined'");
    }
  );
}

async function testNoUndefinedInBadgeTitle() {
  // Old bug: badge referenced data.current_version, which state.cgi never emitted -> literal "undefined".
  await withPage(
    () => ({ sysusage: "CPU: 5% RAM: 1/2 kB", update_available: 1, update_latest_version: "v1.4.0" /* current_version omitted */ }),
    async (page) => {
      const title = await page.$eval("#update_notifier", (el) => el.title);
      ok(!title.includes("undefined"), `badge title must not contain 'undefined' when current_version is absent, got "${title}"`);
    }
  );
}

const tests = [
  assertNoHardcodedVersion,
  testCurrentVersionShown,
  testUpdateAvailableAmber,
  testMissingVersionHandled,
  testNoUndefinedInBadgeTitle,
];

for (const t of tests) {
  try {
    await t();
  } catch (e) {
    fail++;
    console.error("FAIL (exception) in " + t.name + ": " + e.message);
  }
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail > 0 ? 1 : 0);
