import type Cache from "./@types/cache";
import type Manifest from "./@types/manifest";
import { Downloader } from "nodejs-file-downloader";
import ProgressBar from "progress";
import { join } from "path";
import { exists } from "node:fs/promises";
import logger from "./logger";

async function downloadFirefox(version: string) {
  const url = `https://github.com/mauro-balades/warpfox/releases/download/firefox-v${version}/firefox-source.tar.gz`;
  if (await exists(join(process.cwd(), ".warpfox", "firefox-source.tar.gz"))) {
    return;
  }
  logger.info(`Downloading Firefox v${version}`);
  let bar = new ProgressBar("Downloading [:bar] :rate/bps (:percent)", {
    total: 100 * 1000,
    width: 40,
  });
  const downloader = new Downloader({
    url,
    directory: join(process.cwd(), ".warpfox"),
    onProgress: function (percentage, chunk, remainingSize) {
      bar.tick();
    },
  });

  try {
    await downloader.download();
  } catch (error) {
    logger.error(`Failed to download Firefox v${version} (${error})`);
    process.exit(1);
  }
}

export default async function buildCommand({
  manifest,
  cache,
}: {
  manifest: Manifest;
  cache: Cache;
}) {
  await downloadFirefox(manifest.firefoxVersion);
  if (!cache.hasInitialised) {
    //cache.hasInitialised = true;
  }
}
