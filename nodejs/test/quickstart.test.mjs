// Offline tests: mock the SDK client, check each request and the printed output.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mockClient } from "aws-sdk-client-mock";
import {
  DevOpsAgentClient, CreateChatCommand, SendMessageCommand, CreateBacklogTaskCommand,
  GetBacklogTaskCommand, ListExecutionsCommand, ListJournalRecordsCommand, ListRecommendationsCommand,
} from "@aws-sdk/client-devops-agent";
import { ask, investigate, recordText, DONE, NEEDS_YOU } from "../src/quickstart.mjs";

const S = "00000000-0000-0000-0000-000000000000";
const CHAT = "c0000000-0000-4000-8000-000000000001";
const EX = "e0000000-0000-4000-8000-000000000001";
const now = new Date("2026-11-04T14:05:00Z");
const task = (status) => ({ task: { agentSpaceId: S, taskId: "t-1", title: "5xx spike", taskType: "INVESTIGATION",
  priority: "HIGH", status, createdAt: now, updatedAt: now, version: 1 } });

test("ask streams text deltas", async () => {
  const m = mockClient(DevOpsAgentClient);
  m.on(CreateChatCommand, { agentSpaceId: S }).resolves({ executionId: CHAT, createdAt: now });
  m.on(SendMessageCommand, { agentSpaceId: S, executionId: CHAT, content: "Any 5xx?" }).resolves({
    events: (async function* () {
      yield { responseCreated: { responseId: "x" } };
      yield { contentBlockStart: { index: 0, type: "thinking" } };
      yield { contentBlockDelta: { index: 0, delta: { textDelta: { text: "I should check alarms" } } } };
      yield { contentBlockStart: { index: 1, type: "tool_summary" } };
      yield { contentBlockDelta: { index: 1, delta: { textDelta: { text: "Done" } } } };
      yield { contentBlockStart: { index: 2, type: "text" } };
      yield { contentBlockDelta: { index: 2, delta: { textDelta: { text: "Yes, " } } } };
      yield { contentBlockDelta: { index: 2, delta: { textDelta: { text: "3 alarms." } } } };
      yield { contentBlockStart: { index: 3, type: "final_response" } };
      yield { contentBlockDelta: { index: 3, delta: { textDelta: { text: "Yes, 3 alarms." } } } };
      yield { contentBlockStart: { index: 4, type: "chat_title" } };
      yield { contentBlockDelta: { index: 4, delta: { textDelta: { text: "Alarm check" } } } };
      yield { responseCompleted: { responseId: "x" } };
    })(),
  });
  let out = "";
  const text = await ask(new DevOpsAgentClient({ region: "us-east-1" }), S, "Any 5xx?", (t) => { out += t; });
  assert.equal(text, "Yes, 3 alarms.");
  assert.equal(out, "Yes, 3 alarms.\n");
  assert.equal(m.commandCalls(SendMessageCommand).length, 1);
  m.restore();
});

test("ask throws on responseFailed", async () => {
  const m = mockClient(DevOpsAgentClient);
  m.on(CreateChatCommand).resolves({ executionId: CHAT, createdAt: now });
  m.on(SendMessageCommand).resolves({ events: (async function* () {
    yield { responseFailed: { responseId: "x", errorCode: "E", errorMessage: "quota exceeded" } };
  })() });
  await assert.rejects(ask(new DevOpsAgentClient({}), S, "q", () => {}), /quota exceeded/);
  m.restore();
});

test("investigate polls, paginates journal and recommendations, hides noise", async () => {
  const m = mockClient(DevOpsAgentClient);
  m.on(CreateBacklogTaskCommand, { agentSpaceId: S, taskType: "INVESTIGATION", title: "5xx spike",
    description: "ALB 5xx > 5%", priority: "HIGH" }).resolves(task("PENDING_START"));
  m.on(GetBacklogTaskCommand, { agentSpaceId: S, taskId: "t-1" })
    .resolvesOnce(task("WAITING")).resolvesOnce(task("IN_PROGRESS")).resolves(task("COMPLETED"));
  m.on(ListExecutionsCommand, { agentSpaceId: S, taskId: "t-1" }).resolves({ executions: [{
    agentSpaceId: S, executionId: EX, agentSubTask: "oncall", createdAt: now, updatedAt: now, executionStatus: "STOPPED" }] });
  m.on(ListJournalRecordsCommand, { agentSpaceId: S, executionId: EX, order: "ASC" }).resolves({ records: [
    { recordId: "r-1", createdAt: now, recordType: "observation",
      content: '{"type": "observation", "title": "SG 规则被删", "analysis": "ALB target group lost port 443"}' },
    { recordId: "r-2", createdAt: now, recordType: "utilization", content: '{"data": {}}' },
  ], nextToken: "j2" });
  m.on(ListJournalRecordsCommand, { agentSpaceId: S, executionId: EX, order: "ASC", nextToken: "j2" }).resolves({ records: [
    { recordId: "r-3", createdAt: now, recordType: "investigation_result", content: '{"text": "根因：443 端口规则被删除"}' },
  ] });
  m.on(ListRecommendationsCommand, { agentSpaceId: S, taskId: "t-1" }).resolves({ recommendations: [{
    title: "Restore SG rule", priority: "HIGH", content: { summary: "Re-add inbound 443" } }], nextToken: "r2" });
  m.on(ListRecommendationsCommand, { agentSpaceId: S, taskId: "t-1", nextToken: "r2" }).resolves({ recommendations: [{
    title: "Add an alarm", priority: "MEDIUM", content: { summary: "Alarm on 5xx" } }] });
  const lines = [];
  const t = await investigate(new DevOpsAgentClient({}), S, "5xx spike", "ALB 5xx > 5%", { pollMs: 0, log: (l) => lines.push(l) });
  const out = lines.join("\n");
  assert.equal(t.status, "COMPLETED");
  assert.equal(m.commandCalls(GetBacklogTaskCommand).length, 3);
  assert.match(out, /status = WAITING/);
  assert.match(out, /\[14:05:00\] observation: SG 规则被删 - ALB target group lost port 443/);
  assert.match(out, /investigation_result: 根因：443 端口规则被删除/); // page 2
  assert.doesNotMatch(out, /utilization/);
  assert.match(out, /Restore SG rule/);
  assert.match(out, /Add an alarm/); // page 2
  m.restore();
});

async function shortFlow(finalTask, opts = {}) {
  const m = mockClient(DevOpsAgentClient);
  m.on(CreateBacklogTaskCommand).resolves(task("PENDING_START"));
  m.on(GetBacklogTaskCommand).resolves(finalTask);
  m.on(ListExecutionsCommand).resolves({ executions: [] });
  m.on(ListRecommendationsCommand).resolves({ recommendations: [] });
  const lines = [];
  const t = await investigate(new DevOpsAgentClient({}), S, "x", "y", { pollMs: 0, log: (l) => lines.push(l), ...opts });
  m.restore();
  return [t, lines.join("\n")];
}

test("investigate stops on PENDING_CUSTOMER_APPROVAL, prints primary task for LINKED, stops after max wait", async () => {
  let [t, out] = await shortFlow(task("PENDING_CUSTOMER_APPROVAL"));
  assert.equal(t.status, "PENDING_CUSTOMER_APPROVAL");
  assert.match(out, /approval/);
  const linked = task("LINKED");
  Object.assign(linked.task, { primaryTaskId: "t-0", statusReason: "same alarm as t-0" });
  [t, out] = await shortFlow(linked);
  assert.match(out, /merged into task t-0: same alarm as t-0/);
  [t, out] = await shortFlow(task("IN_PROGRESS"), { maxWaitMs: -1 });
  assert.equal(t.status, "PENDING_START");
  assert.match(out, /stop waiting/);
});

test("recordText edge cases do not crash", () => {
  assert.equal(recordText({ recordType: "message", content: "{}" }), null);
  assert.equal(recordText({ recordType: "investigation_result", content: "not json" }), "investigation_result: not json");
  assert.equal(recordText({ recordType: "investigation_result", content: "[1,2]" }), "investigation_result: [1,2]");
  assert.equal(recordText({ recordType: "observation", content: { title: "t", analysis: "a" } }), "observation: t - a");
});

test("SKIPPED and LINKED count as done, WAITING does not", () => {
  for (const s of ["COMPLETED", "FAILED", "TIMED_OUT", "CANCELED", "LINKED", "SKIPPED"]) assert.ok(DONE.has(s), s);
  assert.ok(!DONE.has("WAITING"));
  assert.ok(NEEDS_YOU.has("PENDING_CUSTOMER_APPROVAL"));
});
