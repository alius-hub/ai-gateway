import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

const require = createRequire(import.meta.url);
const vitePackageJsonPath = require.resolve("vite/package.json");
const vitePackageJson = JSON.parse(readFileSync(vitePackageJsonPath, "utf8"));
// Resolve the CLI entry from package metadata so Vite 7+ package exports are respected.
const viteBin = resolve(dirname(vitePackageJsonPath), vitePackageJson.bin.vite);
const commandArgs = process.argv.slice(2);
const envName = (process.env.ENV || "dev").trim().toLowerCase() || "dev";

const args = [...commandArgs];

if (!args.includes("--mode")) {
  args.push("--mode", envName);
}

const child = spawn(process.execPath, [viteBin, ...args], {
  stdio: "inherit",
  env: {
    ...process.env,
    ENV: envName,
  },
});

child.on("exit", (code) => {
  process.exit(code ?? 0);
});
