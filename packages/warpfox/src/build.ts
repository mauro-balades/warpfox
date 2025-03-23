import type Cache from "./@types/cache";
import type Manifest from "./@types/manifest";
import { join } from "path";
import { exists, mkdir } from "node:fs/promises";
import logger from "./logger";
import { commandExistsSync } from "./utils/command-exists";
import { downloadFileToLocation } from "./utils/download";
import { resolve } from "node:path";
import { execa } from "execa";

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

  // On MacOS, we need to use gnu tar, otherwise tar doesn't behave how we
  // would expect it to behave, so this section is responsible for handling
  // that
  //
  // If BSD tar adds --transform support in the future, we can use that
  // instead
  if (process.platform == "darwin") {
    // GNU Tar doesn't come preinstalled on any MacOS machines, so we need to
    // check for it and ask for the user to install it if necessary
    if (!commandExistsSync("gtar")) {
      throw new Error(
        `GNU Tar is required to extract Firefox's source on MacOS. Please install it using the command |brew install gnu-tar| and try again`,
      );
    }

    tarExec = "gtar";
  }

  if (await exists(resolve(tmpDir, "engine"))) {
    return;
  }

  await mkdir(resolve(tmpDir, "engine"), { recursive: true });

  logger.info("Unpacking firefox source");
  if (process.platform === "win32") {
    logger.info("Unpacking Firefox source on Windows (7z)");
    await execa("7z", [
      "x",
      resolve(tmpDir, name),
      "-o" + resolve(tmpDir, name.replace(".tar.xz", ".tar")),
    ]);
    logger.info("Unpacking Firefox source again without the .xz extension");
    await execa("7z", [
      "x",
      resolve(tmpDir, name.replace(".tar.xz", ".tar")),
      "-o" + tmpDir,
    ]);
    const archiveDir = resolve(tmpDir, "firefox-" + version);
    logger.info("Moving Firefox source to engine directory");
    // move the extracted files to the engine directory
    await execa("mv", [archiveDir, outDir]);
    return;
  }

  await execa(
    tarExec,
    ["--strip-components=1", "-xf", resolve(tmpDir, name), "-C", outDir].filter(
      Boolean,
    ) as string[],
  );
}

async function initFirefoxRepo(ffVersion: string) {
  logger.info("Initializing git, this may take some time");
  const absoluteInitDirectory = join(process.cwd(), ".warpfox", "engine");

  await execa("git", {
    args: ["init"],
    cwd: absoluteInitDirectory,
  });

  await execa("git", {
    args: ["init"],
    cwd: absoluteInitDirectory,
  });

  await execa("git", {
    args: ["checkout", "--orphan", ffVersion],
    cwd: absoluteInitDirectory,
  });

  await execa("git", {
    args: ["add", "-f", "."],
    cwd: absoluteInitDirectory,
  });

  logger.info("Committing...");

  await execa("git", {
    args: ["commit", "-aqm", `"Firefox ${ffVersion}"`],
    cwd: absoluteInitDirectory,
  });

  await execa("git", {
    args: ["checkout", "-b", "warpfox_" + ffVersion.replace(/\./g, "_")],
    cwd: absoluteInitDirectory,
  });
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
