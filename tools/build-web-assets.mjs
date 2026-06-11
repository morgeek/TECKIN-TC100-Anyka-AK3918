import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Syncs frontend/src/ to the deployable copies under www/.
// The camera serves the files verbatim (no transpile/minify step — the
// ".min" suffix in target names is historical), so source and target must
// stay byte-identical. Run with --check in CI to fail on drift.
//
// History note: frontend/src was reconstructed 2026-06-11 from the live
// www/ bundles after the original source was deleted in 897e8b5 and the
// bundles kept evolving without it. The bundles were authoritative then;
// frontend/src is authoritative from now on.

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const checkOnly = process.argv.includes("--check");

const assetMap = [
  {
    source: "frontend/src/js/camcontrols.js",
    targets: ["www/scripts/camcontrols.bundle.min.js"],
  },
  {
    source: "frontend/src/js/index.js",
    targets: ["www/scripts/index.bundle.min.js"],
  },
  {
    source: "frontend/src/js/ptt-audio.js",
    targets: ["www/scripts/ptt-audio.bundle.min.js"],
  },
  {
    source: "frontend/src/js/scripts.js",
    targets: ["www/scripts/scripts.bundle.min.js"],
  },
  {
    source: "frontend/src/js/view_records.js",
    targets: ["www/scripts/view_records.bundle.min.js"],
  },
  {
    // The page links ui-modern.min.css; www/css/ui-modern.css is an
    // unreferenced design draft ("deep cobalt") and is left untouched.
    source: "frontend/src/css/ui-modern.css",
    targets: ["www/css/ui-modern.min.css"],
  },
];

async function ensureParentDir(targetPath) {
  await mkdir(path.dirname(targetPath), { recursive: true });
}

async function fileContentOrEmpty(targetPath) {
  try {
    return await readFile(targetPath, "utf8");
  } catch (error) {
    if (error && error.code === "ENOENT") {
      return "";
    }
    throw error;
  }
}

async function syncAsset(entry) {
  const sourcePath = path.join(rootDir, entry.source);
  const sourceText = await readFile(sourcePath, "utf8");
  let changed = false;

  for (const target of entry.targets) {
    const targetPath = path.join(rootDir, target);
    const currentText = await fileContentOrEmpty(targetPath);
    if (currentText === sourceText) {
      console.log(`${checkOnly ? "ok" : "kept"} ${target}`);
      continue;
    }

    changed = true;
    if (checkOnly) {
      console.log(`drift ${target} <- ${entry.source}`);
      continue;
    }

    await ensureParentDir(targetPath);
    await writeFile(targetPath, sourceText, "utf8");
    console.log(`wrote ${target}`);
  }

  return changed;
}

let driftFound = false;
for (const entry of assetMap) {
  const changed = await syncAsset(entry);
  driftFound = driftFound || changed;
}

if (checkOnly && driftFound) {
  process.exitCode = 1;
}
