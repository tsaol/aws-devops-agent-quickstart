// Offline tests for install-skills.mjs (+ optional online check of GitHub URLs: ONLINE=1).
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { unzipSync } from "fflate";
import { mockClient } from "aws-sdk-client-mock";
import { DevOpsAgentClient, CreateAssetCommand, ListAssetsCommand } from "@aws-sdk/client-devops-agent";
import * as ins from "../src/install-skills.mjs";

const HERE = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const S = "00000000-0000-0000-0000-000000000000";
const now = new Date("2026-11-04T00:00:00Z");
const asset = (assetId, name) => ({ assetId, assetType: "skill", metadata: { name }, version: 1, createdAt: now, updatedAt: now });

test("47 skills, valid frontmatter", () => {
  const skills = ins.allSkills();
  assert.equal(skills.length, 47);
  for (const s of skills) {
    const fm = ins.frontmatter(s);
    assert.equal(fm.name, s);
    assert.ok(fm.agentTypes.every((t) => ins.AGENT_TYPES.has(t)), s);
  }
});

test("zips: SKILL.md at root, only runtime files, under 6 MB", () => {
  for (const s of ins.allSkills()) {
    const data = ins.buildZip(s);
    assert.ok(data.length < ins.MAX_ZIP, s);
    const names = Object.keys(unzipSync(data));
    assert.ok(names.includes("SKILL.md"), s);
    for (const n of names) assert.ok(ins.RUNTIME_PARTS.includes(n.split("/")[0]), `${s}: ${n}`);
  }
});

test("--all selection: 35 by default, flags add examples and third-party", () => {
  assert.equal(ins.defaultSkills().length, 35);
  assert.equal(ins.defaultSkills({ includeExamples: true }).length, 37);
  assert.equal(ins.defaultSkills({ includeExamples: true, includeThirdParty: true }).length, 47);
});

test("install: skip existing (paged), zip upload, GitHub import", async () => {
  const m = mockClient(DevOpsAgentClient);
  m.on(ListAssetsCommand, { agentSpaceId: S, assetType: "skill", maxResults: 50 })
    .resolvesOnce({ items: [asset("a-0", "other")], nextToken: "p2" })
    .resolves({ items: [] });
  m.on(ListAssetsCommand, { agentSpaceId: S, assetType: "skill", maxResults: 50, nextToken: "p2" })
    .resolves({ items: [asset("a-1", "aws-health-events")] });
  m.on(CreateAssetCommand).callsFake((input) => ({ asset: asset(`new-${input.metadata.agent_types.join("+")}`, "x") }));
  const c = new DevOpsAgentClient({});
  const quiet = { log: () => {} };
  let r = await ins.install(c, S, ["aws-health-events", "aws-routing"], quiet);
  assert.deepEqual(r, { "aws-health-events": "skipped", "aws-routing": "new-CHAT+INCIDENT_RCA" });
  m.on(ListAssetsCommand, { agentSpaceId: S, assetType: "skill", maxResults: 50 }).resolves({ items: [{ assetId: "a-9", metadata: {} }] });
  r = await ins.install(c, S, ["skip-scheduled-maintenance"], { ...quiet, fromGithub: true });
  assert.deepEqual(r, { "skip-scheduled-maintenance": "new-INCIDENT_TRIAGE" });
  const calls = m.commandCalls(CreateAssetCommand).map((x) => x.args[0].input);
  assert.equal(calls.length, 2);
  // a failure (e.g. no GitHub association) is reported and the next skill still runs
  m.on(CreateAssetCommand, { content: { sourceUrl: { url: ins.GITHUB_TREE + "aws-routing" } } })
    .rejects(Object.assign(new Error("No GitHub access is configured"), { name: "ValidationException" }));
  r = await ins.install(c, S, ["aws-routing", "support-cases"], { ...quiet, fromGithub: true });
  assert.deepEqual(r, { "aws-routing": "failed", "support-cases": "new-CHAT+INCIDENT_RCA" });
  assert.equal(calls[0].assetType, "skill");
  assert.ok(calls[0].content.zip.zipFile instanceof Uint8Array);
  assert.ok(Object.keys(unzipSync(calls[0].content.zip.zipFile)).includes("SKILL.md"));
  assert.deepEqual(calls[1].content, { sourceUrl: { url: ins.GITHUB_TREE + "skip-scheduled-maintenance" } });
  m.restore();
});

test("cli: list, zip, refuse install without AGENT_SPACE_ID", () => {
  const env = { ...process.env, AGENT_SPACE_ID: "" };
  const out = execFileSync(process.execPath, ["src/install-skills.mjs", "list"], { cwd: HERE, env, encoding: "utf8" });
  assert.equal(out.trim().split("\n").length, 47);
  assert.match(out, /skip-scheduled-maintenance .*\(example\)/);
  execFileSync(process.execPath, ["src/install-skills.mjs", "zip", "aws-routing"], { cwd: HERE, env });
  const z = path.join(HERE, "dist", "aws-routing.zip");
  assert.ok(fs.existsSync(z));
  fs.rmSync(path.join(HERE, "dist"), { recursive: true });
  const fails = (args, want, extraEnv = {}) => {
    const r = spawnSync(process.execPath, ["src/install-skills.mjs", ...args], { cwd: HERE, env: { ...env, ...extraEnv }, encoding: "utf8" });
    assert.equal(r.status, 2, `${args}: ${r.stderr}`);
    assert.match(r.stderr, want);
  };
  fails(["install", "aws-routing"], /AGENT_SPACE_ID/);
  fails(["zip", "aws-rooting"], /unknown skills: aws-rooting/); // typo -> error, not an empty zip
  fails(["install", "--al"], /unknown option: --al/);
  fails(["install", "--all", "aws-routing"], /either --all or skill names/, { AGENT_SPACE_ID: S });
  assert.throws(() => ins.buildZip("aws-rooting"), /unknown skill/);
});

test("bin entry works through a symlink (npm link / npx)", () => {
  const dir = fs.mkdtempSync(path.join(HERE, ".bin-test-"));
  try {
    const link = path.join(dir, "install-skills");
    fs.symlinkSync(path.join(HERE, "src", "install-skills.mjs"), link);
    const out = execFileSync(process.execPath, [link, "list"], { env: { ...process.env, AGENT_SPACE_ID: "" }, encoding: "utf8" });
    assert.equal(out.trim().split("\n").length, 47);
  } finally {
    fs.rmSync(dir, { recursive: true });
  }
});

test("online: every GitHub skill URL opens", { skip: !process.env.ONLINE }, async () => {
  const bad = [];
  for (const s of ins.allSkills()) {
    const res = await fetch(ins.GITHUB_TREE + s, { method: "HEAD" });
    if (res.status !== 200) bad.push([s, res.status]);
  }
  assert.deepEqual(bad, []);
});
