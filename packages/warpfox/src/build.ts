import type Cache from "./@types/cache";
import type Manifest from "./@types/manifest";
import { join } from "path";
import { exists, mkdir } from "node:fs/promises";
import logger from "./logger";
import { commandExistsSync } from "./utils/command-exists";
import { downloadFileToLocation } from "./utils/download";
import { resolve } from "node:path";
import { $ } from "bun";
import spawn from "cross-spawn";

async function downloadFirefox(version: string) {
  const url = `https://github.com/mauro-balades/warpfox/releases/download/firefox-v${version}/firefox-source.tar.gz`;
  const out = join(process.cwd(), ".warpfox", "firefox-source.tar.gz");
  if (await exists(out)) {
    return;
  }
  logger.info(`Downloading Firefox v${version}`);
  await downloadFileToLocation(url, out);
}

async function unpackFirefox(version: string) {
  let tarExec = "tar";
  const tmpDir = join(process.cwd(), ".warpfox");
  const name = `firefox-source.tar.gz`;
  const outDir = join(tmpDir, "engine");

  if (await exists(resolve(tmpDir, "engine"))) {
    return;
  }

  await mkdir(resolve(tmpDir, "engine"), { recursive: true });

  logger.info("Unpacking firefox source");
  $`${tarExec} --strip-components=2 -xf ${resolve(tmpDir, name)} -C ${outDir}`;
}

async function initFirefoxRepo(ffVersion: string) {
  logger.info("Initializing git, this may take some time");
  const absoluteInitDirectory = join(process.cwd(), ".warpfox", "engine");

  await spawn("git", ["init"], {
    cwd: absoluteInitDirectory,
  });

  await spawn("git", ["checkout", "--orphan", ffVersion], {
    cwd: absoluteInitDirectory,
  });

  await spawn("git", ["add", "-f", "."], {
    cwd: absoluteInitDirectory,
  });

  logger.info("Committing...");

  await spawn("git", ["commit", "-aqm", `"Firefox ${ffVersion}"`], {
    cwd: absoluteInitDirectory,
  });

  await spawn(
    "git",
    ["checkout", "-b", "warpfox_" + ffVersion.replace(/\./g, "_")],
    {
      cwd: absoluteInitDirectory,
    },
  );
}

export default async function buildCommand({
  manifest,
  cache,
}: {
  manifest: Manifest;
  cache: Cache;
}) {
  const ffVersion = manifest.firefoxVersion;
  await downloadFirefox(ffVersion);
  await unpackFirefox(ffVersion);
  if (!cache.hasInitialised) {
    await initFirefoxRepo(ffVersion);
  }
  cache.hasInitialised = true;
}
