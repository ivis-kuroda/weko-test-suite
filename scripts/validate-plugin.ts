/**
 * Validates plugin.yaml against the hub's manifest schema.
 *
 * The hub is imported by path so its own dependencies (zod, yaml) resolve.
 * Usage: node scripts/validate-plugin.ts <hub-dir> <plugin.yaml>
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [hubDir, pluginPath] = process.argv.slice(2);
if (hubDir === undefined || pluginPath === undefined) {
  process.stderr.write("usage: validate-plugin.ts <hub-dir> <plugin.yaml>\n");
  process.exit(2);
}

const { loadManifest } = (await import(
  pathToFileURL(resolve(hubDir, "packages/plugin/src/index.ts")).href
)) as { loadManifest: (source: string) => { manifest: { operations: object } } };

try {
  const { manifest } = loadManifest(readFileSync(pluginPath, "utf8"));
  process.stdout.write(`${pluginPath}: ${Object.keys(manifest.operations).length} operation(s) ok\n`);
} catch (error) {
  process.stderr.write(`${pluginPath}: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
}
