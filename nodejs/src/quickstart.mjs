#!/usr/bin/env node
// AWS DevOps Agent quick start (Node.js, AWS SDK v3).
//
//   node src/quickstart.mjs ask "Which alarms fired in the last 24 hours?"
//   node src/quickstart.mjs investigate "5xx spike on checkout API" "Started 14:05 UTC, ALB 5xx > 5%"
//
// Env: AGENT_SPACE_ID (required), AWS_REGION (default us-east-1)
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
import { pathToFileURL } from "node:url";

export const DONE = new Set(["COMPLETED", "FAILED", "TIMED_OUT", "CANCELED", "LINKED", "SKIPPED"]);

export function makeClient() {
  return new DevOpsAgentClient({ region: process.env.AWS_REGION || "us-east-1" });
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
  const title = keys[0] ? c[keys[0]] : null;
  const body = c[keys[1]] ?? "";
  return title ? `${record.recordType}: ${title} - ${body}` : `${record.recordType}: ${body}`;
}

/** Start an investigation, wait for it, print the steps and recommendations. */
export async function investigate(client, space, title, description = "", { priority = "HIGH", pollMs = 30000, log = console.log } = {}) {
  let { task } = await client.send(
    new CreateBacklogTaskCommand({ agentSpaceId: space, taskType: "INVESTIGATION", title, description, priority }),
  );
  const taskId = task.taskId;
  log(`task ${taskId}: ${task.status}`);

  while (!DONE.has(task.status)) {
    await sleep(pollMs);
    ({ task } = await client.send(new GetBacklogTaskCommand({ agentSpaceId: space, taskId })));
    log(`  status = ${task.status}`);
  }

  // What the agent did: executions -> journal records
  const { executions } = await client.send(new ListExecutionsCommand({ agentSpaceId: space, taskId }));
  for (const ex of executions) {
    log(`\n== execution ${ex.executionId} (${ex.agentSubTask}, ${ex.executionStatus})`);
    const { records } = await client.send(
      new ListJournalRecordsCommand({ agentSpaceId: space, executionId: ex.executionId, order: "ASC" }),
    );
    for (const r of records) {
      const line = recordText(r);
      if (line) log(`  [${new Date(r.createdAt).toISOString().slice(11, 19)}] ${line}`);
    }
  }

  // What the agent suggests
  const { recommendations } = await client.send(new ListRecommendationsCommand({ agentSpaceId: space, taskId }));
  for (const rec of recommendations) {
    log(`\n* [${rec.priority}] ${rec.title}\n  ${rec.content.summary}`);
  }
  return task;
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

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).catch((e) => {
    console.error(`${e.name}: ${e.message}`);
    process.exit(1);
  });
}
