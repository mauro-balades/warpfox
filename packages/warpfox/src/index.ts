import buildCommand from "./build";
import logger from "./logger";
import { parseArgs } from "util";
import getManifestContent from "./manifest";
import { getSavedCache, saveCache } from "./cache";

async function main(): Promise<number> {
  const args = parseArgs({
    args: Bun.argv,
    allowPositionals: true,
  });
  const command = args.positionals[args.positionals.length - 1];
  let manifest;
  try {
    manifest = await getManifestContent();
  } catch (error) {
    logger.error(`Failed to read warpfox.manifest.json (${error})`);
    return 1;
  }
  const cache = await getSavedCache();
  const startTime = Date.now();
  let exitCode = 0;
  switch (command) {
    case "build":
      await buildCommand({ manifest, cache });
      break;
    default:
      logger.error(`Unknown command: ${command}`);
      exitCode = 1;
  }
  await saveCache(cache);
  if (exitCode === 0) {
    logger.info(`Done in ${Date.now() - startTime}ms`);
  }
  return exitCode;
}

process.exit(await main());
