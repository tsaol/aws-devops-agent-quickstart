#!/usr/bin/env node
// AWS DevOps Agent quick start (Node.js, AWS SDK v3).
//
//   node src/quickstart.mjs ask "Which alarms fired in the last 24 hours?"
//   node src/quickstart.mjs investigate "5xx spike on checkout API" "Started 14:05 UTC, ALB 5xx > 5%"
//
// Env: AGENT_SPACE_ID (required)
//      AWS_REGION, else AWS_DEFAULT_REGION, else us-east-1 (the Agent Space Region)
//      MAX_WAIT_MINUTES (default 60) for investigate
import {
  DevOpsAgentClient,
  CreateChatCommand,
  SendMessageCommand,
  CreateBacklogTaskCommand,
  GetBacklogTaskCommand,
  ListExecutionsCommand,
  ListJournalRecordsCommand,
  ListRecommendationsCommand,
} from "@aws-sdk/client-devops-agent";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

export const DONE = new Set(["COMPLETED", "FAILED", "TIMED_OUT", "CANCELED", "LINKED", "SKIPPED"]);
// Needs a person: approve or reject the mitigation plan in the Agent Space web app.
export const NEEDS_YOU = new Set(["PENDING_CUSTOMER_APPROVAL"]);

export function makeClient() {
  return new DevOpsAgentClient({ region: process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || "us-east-1" });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Chat: one question, stream the answer. Returns the answer text.
 * The stream has several content blocks: thinking, tool_summary, text, final_response,
 * chat_title... Only "text" is the answer. "final_response" repeats it, so it is used
 * only if no "text" block came.
 */
export async function ask(client, space, question, write = (t) => process.stdout.write(t)) {
  const { executionId } = await client.send(new CreateChatCommand({ agentSpaceId: space }));
  const resp = await client.send(
    new SendMessageCommand({ agentSpaceId: space, executionId, content: question }),
  );
  const blockType = {};
  let answer = "";
  let fallback = "";
  for await (const event of resp.events) {
    if (event.contentBlockStart) blockType[event.contentBlockStart.index] = event.contentBlockStart.type;
    const d = event.contentBlockDelta;
    const t = d?.delta?.textDelta?.text;
    if (t && blockType[d.index] === "text") {
      answer += t;
      write(t);
    } else if (t && blockType[d.index] === "final_response") {
      fallback += t;
    }
    if (event.responseFailed) throw new Error(event.responseFailed.errorMessage);
  }
  if (!answer && fallback) {
    answer = fallback;
    write(fallback);
  }
  write("\n");
  return answer;
}

// Journal record types worth showing. The rest (message, utilization,
// ui_investigation_summary, ...) is raw model traffic or data for the web UI.
export const SHOW = {
  observation: ["title", "analysis"],
  investigation_gap: ["title", "description"],
  root_cause: ["title", "description"],
  mitigation: ["title", "description"],
  investigation_result: [null, "text"],
};

/** Short readable line for a journal record, or null to skip it. `content` comes back as a JSON string. */
export function recordText(record) {
  const keys = SHOW[record.recordType];
  if (!keys) return null;
  let c = record.content;
  if (typeof c === "string") {
    try { c = JSON.parse(c); } catch { return `${record.recordType}: ${c}`; }
  }
  if (!c || typeof c !== "object" || Array.isArray(c)) return `${record.recordType}: ${JSON.stringify(c)}`;
  const title = keys[0] ? c[keys[0]] : null;
  const body = c[keys[1]] ?? "";
  return title ? `${record.recordType}: ${title} - ${body}` : `${record.recordType}: ${body}`;
}

/** Follow nextToken until the last page. */
export async function allPages(client, Command, input, key) {
  const items = [];
  let nextToken;
  do {
    const page = await client.send(new Command({ ...input, ...(nextToken && { nextToken }) }));
    items.push(...(page[key] || []));
    nextToken = page.nextToken;
  } while (nextToken);
  return items;
}

/** Start an investigation, wait for it, print the steps and recommendations. */
export async function investigate(client, space, title, description = "", {
  priority = "HIGH", pollMs = 30000, maxWaitMs = Number(process.env.MAX_WAIT_MINUTES || 60) * 60000, log = console.log,
} = {}) {
  let { task } = await client.send(
    new CreateBacklogTaskCommand({ agentSpaceId: space, taskType: "INVESTIGATION", title, description, priority }),
  );
  const taskId = task.taskId;
  log(`task ${taskId}: ${task.status}`);

  const deadline = Date.now() + maxWaitMs;
  while (!DONE.has(task.status) && !NEEDS_YOU.has(task.status)) {
    if (Date.now() > deadline) {
      log(`  still ${task.status} after ${Math.round(maxWaitMs / 60000)} min, stop waiting (check task ${taskId} in the web app)`);
      break;
    }
    await sleep(pollMs);
    ({ task } = await client.send(new GetBacklogTaskCommand({ agentSpaceId: space, taskId })));
    log(`  status = ${task.status}`);
  }
  if (NEEDS_YOU.has(task.status)) log("  waiting for your approval in the Agent Space web app");
  if (task.status === "LINKED") log(`  merged into task ${task.primaryTaskId}: ${task.statusReason || ""}`);
  else if (task.statusReason) log(`  reason: ${task.statusReason}`);

  // What the agent did: executions -> journal records (all pages)
  const executions = await allPages(client, ListExecutionsCommand, { agentSpaceId: space, taskId }, "executions");
  for (const ex of executions) {
    log(`\n== execution ${ex.executionId} (${ex.agentSubTask}, ${ex.executionStatus})`);
    const records = await allPages(client, ListJournalRecordsCommand,
      { agentSpaceId: space, executionId: ex.executionId, order: "ASC" }, "records");
    for (const r of records) {
      const line = recordText(r);
      if (line) log(`  [${new Date(r.createdAt).toISOString().slice(11, 19)}] ${line}`);
    }
  }

  // What the agent suggests
  const recommendations = await allPages(client, ListRecommendationsCommand, { agentSpaceId: space, taskId }, "recommendations");
  for (const rec of recommendations) {
    log(`\n* [${rec.priority}] ${rec.title}\n  ${rec.content.summary}`);
  }
  return task;
}

/** True when this file is the program being run (also through an npm bin symlink). */
export function isMain(metaUrl) {
  if (!process.argv[1]) return false;
  try {
    return metaUrl === pathToFileURL(fs.realpathSync(process.argv[1])).href;
  } catch {
    return false;
  }
}

async function main(argv) {
  const usage = 'usage: quickstart.mjs ask "<question>" | investigate "<title>" ["<description>"]';
  const space = process.env.AGENT_SPACE_ID;
  const [cmd, a, b] = argv;
  if (!space || !a || !["ask", "investigate"].includes(cmd)) {
    console.error(space ? usage : "set AGENT_SPACE_ID first\n" + usage);
    process.exit(2);
  }
  const client = makeClient();
  if (cmd === "ask") await ask(client, space, a);
  else await investigate(client, space, a, b || "");
}

if (isMain(import.meta.url)) {
  main(process.argv.slice(2)).catch((e) => {
    console.error(`${e.name}: ${e.message}`);
    process.exit(1);
  });
}
