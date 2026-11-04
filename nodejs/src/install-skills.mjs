#!/usr/bin/env node
// Install the official skills in tools-for-devops-agent/skills/ into an Agent Space (Node.js).
//
//   node src/install-skills.mjs list
//   node src/install-skills.mjs installed
//   node src/install-skills.mjs install aws-health-events aws-routing
//   node src/install-skills.mjs install --all               # skips examples and third-party skills
//   node src/install-skills.mjs install --all --include-examples --include-third-party
//   node src/install-skills.mjs install aws-routing --from-github
//   node src/install-skills.mjs zip aws-routing             # only build dist/aws-routing.zip
//
// Env: AGENT_SPACE_ID (not needed for list / zip), AWS_REGION (default us-east-1)
// IAM: aidevops:CreateAsset, aidevops:ListAssets
import { CreateAssetCommand, ListAssetsCommand } from "@aws-sdk/client-devops-agent";
import { zipSync } from "fflate";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { makeClient } from "./quickstart.mjs";

const HERE = path.dirname(path.dirname(fileURLToPath(import.meta.url))); // nodejs/
export const SKILLS_DIR = path.join(HERE, "..", "tools-for-devops-agent", "skills");
const DIST = path.join(HERE, "dist");
export const GITHUB_TREE = "https://github.com/aws/tools-for-devops-agent/tree/main/skills/";
export const RUNTIME_PARTS = ["SKILL.md", "references", "assets"]; // what the agent reads
export const MAX_ZIP = 6 * 1024 * 1024;
export const AGENT_TYPES = new Set(["GENERIC", "CHAT", "INCIDENT_TRIAGE", "INCIDENT_RCA", "INCIDENT_MITIGATION",
  "INCIDENT_UI", "PREVENTION", "RELEASE_READINESS_REVIEW", "RELEASE_TESTING"]);
// --all skips these unless asked. You can still install them by name.
export const EXAMPLES = new Set([
  "crm-production-investigation-guidelines", // triage rules for a demo CRM app; turns off incident linking
  "skip-scheduled-maintenance", // fixed sample window 2025-03-15
]);
export const THIRD_PARTY_PREFIXES = ["honeycomb-", "grafana-", "sumo-logic-", "wiz-"];
const isThirdParty = (s) => THIRD_PARTY_PREFIXES.some((p) => s.startsWith(p));

export function allSkills() {
  return fs.readdirSync(SKILLS_DIR)
    .filter((d) => fs.existsSync(path.join(SKILLS_DIR, d, "SKILL.md")))
    .sort();
}

export function frontmatter(skill) {
  const text = fs.readFileSync(path.join(SKILLS_DIR, skill, "SKILL.md"), "utf8");
  const m = text.match(/^---\n([\s\S]*?)\n---/);
  if (!m) throw new Error(`${skill}: SKILL.md has no frontmatter`);
  const name = m[1].match(/^name:\s*['"]?([\w-]+)/m)[1];
  const at = m[1].match(/aws-devops-agent-skills\.agent-types:\s*['"]?([^'"\n]+)/);
  const agentTypes = at ? at[1].split(",").map((t) => t.trim()) : ["GENERIC"];
  const bad = agentTypes.filter((t) => !AGENT_TYPES.has(t));
  if (bad.length) throw new Error(`${skill}: unknown agent types ${bad}`);
  return { name, agentTypes };
}

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]);
}

/** Zip only SKILL.md, references/ and assets/, with SKILL.md at the zip root. */
export function buildZip(skill) {
  const src = path.join(SKILLS_DIR, skill);
  const files = {};
  for (const part of RUNTIME_PARTS) {
    const p = path.join(src, part);
    if (!fs.existsSync(p)) continue;
    const list = fs.statSync(p).isDirectory() ? walk(p).sort() : [p];
    for (const f of list) files[path.relative(src, f).split(path.sep).join("/")] = fs.readFileSync(f);
  }
  const data = zipSync(files, { level: 6 });
  if (data.length > MAX_ZIP) throw new Error(`${skill}: zip is ${data.length} bytes, over the 6 MB limit`);
  return data;
}

export function defaultSkills({ includeExamples = false, includeThirdParty = false } = {}) {
  return allSkills().filter((s) =>
    (includeExamples || !EXAMPLES.has(s)) && (includeThirdParty || !isThirdParty(s)));
}

export async function installedNames(client, space) {
  const names = {};
  let nextToken;
  do {
    const page = await client.send(new ListAssetsCommand({
      agentSpaceId: space, assetType: "skill", maxResults: 50, ...(nextToken && { nextToken }),
    }));
    for (const a of page.items) names[a.metadata?.name] = a.assetId;
    nextToken = page.nextToken;
  } while (nextToken);
  return names;
}

export async function install(client, space, skills, { fromGithub = false, log = console.log } = {}) {
  const have = await installedNames(client, space);
  const results = {};
  for (const s of skills) {
    const fm = frontmatter(s);
    if (have[fm.name]) {
      log(`skip    ${s} (already installed: ${have[fm.name]})`);
      results[s] = "skipped";
      continue;
    }
    const content = fromGithub ? { sourceUrl: { url: GITHUB_TREE + s } } : { zip: { zipFile: buildZip(s) } };
    let asset;
    try {
      ({ asset } = await client.send(new CreateAssetCommand({
        agentSpaceId: space, assetType: "skill", metadata: { agent_types: fm.agentTypes }, content,
      })));
    } catch (e) { // e.g. --from-github without a GitHub association
      log(`FAILED  ${s}: ${e.name}: ${e.message}`);
      results[s] = "failed";
      continue;
    }
    log(`install ${s} -> ${asset.assetId} ${JSON.stringify(fm.agentTypes)}`);
    results[s] = asset.assetId;
  }
  return results;
}

async function main(argv) {
  const [cmd, ...args] = argv;
  const tag = (s) => (EXAMPLES.has(s) ? " (example)" : isThirdParty(s) ? " (third-party)" : "");
  if (cmd === "list") {
    for (const s of allSkills()) console.log(`${s.padEnd(45)} ${frontmatter(s).agentTypes.join(",")}${tag(s)}`);
    return;
  }
  if (cmd === "zip") {
    fs.mkdirSync(DIST, { recursive: true });
    for (const s of args.length ? args : allSkills()) {
      const out = path.join(DIST, `${s}.zip`);
      fs.writeFileSync(out, buildZip(s));
      console.log(`${out}  ${Math.floor(fs.statSync(out).size / 1024)} KB`);
    }
    return;
  }
  const space = process.env.AGENT_SPACE_ID;
  if (!space) { console.error("set AGENT_SPACE_ID first"); process.exit(2); }
  const client = makeClient();
  if (cmd === "installed") {
    const names = await installedNames(client, space);
    for (const n of Object.keys(names).sort()) console.log(`${String(n).padEnd(45)} ${names[n]}`);
  } else if (cmd === "install") {
    const names = args.filter((a) => !a.startsWith("--"));
    let skills = names;
    if (args.includes("--all")) {
      skills = defaultSkills({
        includeExamples: args.includes("--include-examples"),
        includeThirdParty: args.includes("--include-third-party"),
      });
      const skipped = allSkills().filter((s) => !skills.includes(s));
      if (skipped.length) console.log(`--all skips ${skipped.length} (examples / third-party): ${skipped.join(", ")}`);
    }
    const unknown = skills.filter((s) => !allSkills().includes(s));
    if (!skills.length || unknown.length) {
      console.error(unknown.length ? `unknown skills: ${unknown}` : "name skills or use --all");
      process.exit(2);
    }
    const results = await install(client, space, skills, { fromGithub: args.includes("--from-github") });
    if (Object.values(results).includes("failed")) process.exit(1);
  } else {
    console.error("usage: install-skills.mjs list | zip [skill...] | installed | install <skill...>|--all [--from-github]");
    process.exit(2);
  }
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).catch((e) => {
    console.error(`${e.name}: ${e.message}`);
    process.exit(1);
  });
}
