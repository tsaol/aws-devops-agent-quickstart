"""AWS DevOps Agent quick start (boto3).

  python devops_agent_quickstart.py ask   "Which alarms fired in the last 24 hours?"
  python devops_agent_quickstart.py investigate "5xx spike on checkout API" "Started 14:05 UTC, ALB 5xx > 5%"

Env: AGENT_SPACE_ID (required), AWS_REGION (default us-east-1)
"""
import os
import sys
import time

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
SPACE = os.environ.get("AGENT_SPACE_ID", "")
DONE = {"COMPLETED", "FAILED", "TIMED_OUT", "CANCELED", "LINKED", "SKIPPED"}

client = boto3.client("devops-agent", region_name=REGION)


def ask(question):
    """Chat: one question, stream the answer to stdout."""
    chat = client.create_chat(agentSpaceId=SPACE)
    resp = client.send_message(
        agentSpaceId=SPACE, executionId=chat["executionId"], content=question
    )
    for event in resp["events"]:
        delta = event.get("contentBlockDelta", {}).get("delta", {})
        if "textDelta" in delta:
            print(delta["textDelta"]["text"], end="", flush=True)
        if "responseFailed" in event:
            raise RuntimeError(event["responseFailed"].get("errorMessage"))
    print()
    return chat["executionId"]


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
            print(f"  [{r['createdAt']:%H:%M:%S}] {r['recordType']}: {str(r['content'])[:200]}")

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
