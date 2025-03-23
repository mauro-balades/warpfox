import type Cache from "./@types/cache";
import { mkdir, exists } from "node:fs/promises";
import { join } from "path";
import { file } from "bun";

export async function getSavedCache(): Promise<Cache> {
  const cacheDir = join(process.cwd(), ".warpfox");
  if (!(await exists(cacheDir))) {
    await mkdir(cacheDir);
  }
  try {
    return await file(join(cacheDir, "cache.json")).json();
  } catch {
    return { hasInitialised: false };
  }
}

export async function saveCache(cache: Cache): Promise<void> {
  const cacheDir = join(process.cwd(), ".warpfox");
  if (!(await exists(cacheDir))) {
    await mkdir(cacheDir);
  }
  await Bun.write(join(cacheDir, "cache.json"), JSON.stringify(cache));
}
