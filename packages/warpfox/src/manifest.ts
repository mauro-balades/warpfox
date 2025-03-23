import type Manifest from "./@types/manifest";
import { version as firefoxVersion } from "../firefox.json";
import { join } from "path";

export default async function getManifestContent(): Promise<Manifest> {
  const path = join(process.cwd(), "warpfox.manifest.json");
  return {
    ...(await (Bun.file(path).json() as Promise<Manifest>)),
    firefoxVersion,
  };
}
