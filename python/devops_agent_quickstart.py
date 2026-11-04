"""AWS DevOps Agent quick start (boto3).

  python devops_agent_quickstart.py ask "Which alarms fired in the last 24 hours?"
  python devops_agent_quickstart.py investigate "5xx spike on checkout API" "Started 14:05 UTC, ALB 5xx > 5%"

Env: AGENT_SPACE_ID (required)
     AWS_REGION, else AWS_DEFAULT_REGION, else us-east-1 (the Agent Space Region)
     MAX_WAIT_MINUTES (default 60) for investigate
"""
import datetime as dt
import json
import os
import sys
import time

import boto3

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
SPACE = os.environ.get("AGENT_SPACE_ID", "")
DONE = {"COMPLETED", "FAILED", "TIMED_OUT", "CANCELED", "LINKED", "SKIPPED"}
# Needs a person: approve or reject the mitigation plan in the Agent Space web app.
NEEDS_YOU = {"PENDING_CUSTOMER_APPROVAL"}

# Journal record types worth showing: type -> (title field, body field). The rest
# (message, utilization, ui_investigation_summary, ...) is raw model traffic or web UI data.
SHOW = {
    "observation": ("title", "analysis"),
    "investigation_gap": ("title", "description"),
    "root_cause": ("title", "description"),
    "mitigation": ("title", "description"),
    "investigation_result": (None, "text"),
}

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
    if not isinstance(c, dict):
        return f"{kind}: {c}"
    title_key, body_key = SHOW[kind]
    title = c.get(title_key) if title_key else None
    body = c.get(body_key) or ""
    return f"{kind}: {title} - {body}" if title else f"{kind}: {body}"


def all_pages(op, key, **kw):
    """Follow nextToken until the last page."""
    token = None
    while True:
        page = op(**kw, **({"nextToken": token} if token else {}))
        yield from page.get(key, [])
        token = page.get("nextToken")
        if not token:
            return


def investigate(title, description, priority="HIGH", poll_seconds=30, max_wait_seconds=None):
    """Start an investigation, wait for it, print the steps and recommendations."""
    if max_wait_seconds is None:
        max_wait_seconds = int(os.environ.get("MAX_WAIT_MINUTES", "60")) * 60
    task = client.create_backlog_task(
        agentSpaceId=SPACE,
        taskType="INVESTIGATION",
        title=title,
        description=description,
        priority=priority,
    )["task"]
    task_id = task["taskId"]
    print(f"task {task_id}: {task['status']}")

    deadline = time.monotonic() + max_wait_seconds
    while task["status"] not in DONE | NEEDS_YOU:
        if time.monotonic() > deadline:
            print(f"  still {task['status']} after {max_wait_seconds // 60} min, stop waiting "
                  f"(check task {task_id} in the web app)")
            break
        time.sleep(poll_seconds)
        task = client.get_backlog_task(agentSpaceId=SPACE, taskId=task_id)["task"]
        print(f"  status = {task['status']}")

    if task["status"] in NEEDS_YOU:
        print("  waiting for your approval in the Agent Space web app")
    if task["status"] == "LINKED":
        print(f"  merged into task {task.get('primaryTaskId')}: {task.get('statusReason', '')}")
    elif task.get("statusReason"):
        print(f"  reason: {task['statusReason']}")

    # What the agent did: executions -> journal records (all pages)
    for ex in client.get_paginator("list_executions").paginate(
            agentSpaceId=SPACE, taskId=task_id).search("executions[]"):
        print(f"\n== execution {ex['executionId']} ({ex['agentSubTask']}, {ex['executionStatus']})")
        for r in client.get_paginator("list_journal_records").paginate(
                agentSpaceId=SPACE, executionId=ex["executionId"], order="ASC").search("records[]"):
            line = record_text(r)
            if line:
                print(f"  [{r['createdAt'].astimezone(dt.timezone.utc):%H:%M:%S}] {line}")

    # What the agent suggests (no boto3 paginator for this one)
    for rec in all_pages(client.list_recommendations, "recommendations",
                         agentSpaceId=SPACE, taskId=task_id):
        print(f"\n* [{rec['priority']}] {rec['title']}\n  {rec['content']['summary']}")
    return task


def usage(msg=None):
    if msg:
        print(msg, file=sys.stderr)
    print(__doc__, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    if not SPACE:
        usage("set AGENT_SPACE_ID first")
    if len(sys.argv) < 3:
        usage()
    if sys.argv[1] == "ask":
        ask(sys.argv[2])
    elif sys.argv[1] == "investigate":
        investigate(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    else:
        usage()
