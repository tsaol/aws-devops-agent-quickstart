"""AWS DevOps Agent quick start (boto3).

  python devops_agent_quickstart.py ask   "Which alarms fired in the last 24 hours?"
  python devops_agent_quickstart.py investigate "5xx spike on checkout API" "Started 14:05 UTC, ALB 5xx > 5%"

Env: AGENT_SPACE_ID (required), AWS_REGION (default us-east-1)
"""
import json
import os
import sys
import time

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
SPACE = os.environ.get("AGENT_SPACE_ID", "")
# Journal record types worth showing. The rest (message, utilization,
# ui_investigation_summary, ...) is raw model traffic or data for the web UI.
SHOW = {
    "observation": ("title", "analysis"),
    "investigation_gap": ("title", "description"),
    "root_cause": ("title", "description"),
    "mitigation": ("title", "description"),
    "investigation_result": (None, "text"),
}
DONE = {"COMPLETED", "FAILED", "TIMED_OUT", "CANCELED", "LINKED", "SKIPPED"}

client = boto3.client("devops-agent", region_name=REGION)


def ask(question, write=None):
    """Chat: one question, stream the answer. Returns the answer text.

    The stream has several content blocks: thinking, tool_summary, text,
    final_response, chat_title... Only "text" is the answer. "final_response"
    repeats it, so it is used only if no "text" block came.
    """
    write = write or (lambda t: print(t, end="", flush=True))
    chat = client.create_chat(agentSpaceId=SPACE)
    resp = client.send_message(
        agentSpaceId=SPACE, executionId=chat["executionId"], content=question
    )
    block_type, answer, fallback = {}, [], []
    for event in resp["events"]:
        if "contentBlockStart" in event:
            block_type[event["contentBlockStart"]["index"]] = event["contentBlockStart"].get("type")
        elif "contentBlockDelta" in event:
            d = event["contentBlockDelta"]
            text = d.get("delta", {}).get("textDelta", {}).get("text")
            kind = block_type.get(d.get("index"))
            if text and kind == "text":
                answer.append(text)
                write(text)
            elif text and kind == "final_response":
                fallback.append(text)
        elif "responseFailed" in event:
            raise RuntimeError(event["responseFailed"].get("errorMessage"))
    if not answer and fallback:
        answer = fallback
        write("".join(fallback))
    write("\n")
    return "".join(answer)


def record_text(record):
    """Short readable line for a journal record, or None to skip it.
    `content` comes back as a JSON string."""
    kind = record["recordType"]
    if kind not in SHOW:
        return None
    c = record["content"]
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except ValueError:
            return f"{kind}: {c}"
    title_key, body_key = SHOW[kind]
    title = c.get(title_key) if title_key else None
    body = c.get(body_key) or ""
    return f"{kind}: {title} - {body}" if title else f"{kind}: {body}"


def investigate(title, description, priority="HIGH", poll_seconds=30):
    """Start an investigation, wait for it, print the steps and recommendations."""
    task = client.create_backlog_task(
        agentSpaceId=SPACE,
        taskType="INVESTIGATION",
        title=title,
        description=description,
        priority=priority,
    )["task"]
    task_id = task["taskId"]
    print(f"task {task_id}: {task['status']}")

    while task["status"] not in DONE:
        time.sleep(poll_seconds)
        task = client.get_backlog_task(agentSpaceId=SPACE, taskId=task_id)["task"]
        print(f"  status = {task['status']}")

    # What the agent did: executions -> journal records
    for ex in client.list_executions(agentSpaceId=SPACE, taskId=task_id)["executions"]:
        print(f"\n== execution {ex['executionId']} ({ex['agentSubTask']}, {ex['executionStatus']})")
        records = client.list_journal_records(
            agentSpaceId=SPACE, executionId=ex["executionId"], order="ASC"
        )["records"]
        for r in records:
            line = record_text(r)
            if line:
                print(f"  [{r['createdAt']:%H:%M:%S}] {line}")

    # What the agent suggests
    for rec in client.list_recommendations(agentSpaceId=SPACE, taskId=task_id)["recommendations"]:
        print(f"\n* [{rec['priority']}] {rec['title']}\n  {rec['content']['summary']}")
    return task


if __name__ == "__main__":
    if not SPACE or len(sys.argv) < 3:
        sys.exit(__doc__)
    if sys.argv[1] == "ask":
        ask(sys.argv[2])
    elif sys.argv[1] == "investigate":
        investigate(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    else:
        sys.exit(__doc__)
