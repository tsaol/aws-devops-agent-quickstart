"""5.2 Start an investigation and wait for it.

  python s52_start_investigation.py "API 5xx 升高" "14:05 UTC 起 ALB 5xx 超过 5%，影响结账接口"
  python s52_start_investigation.py "..." "..." --no-wait     # only create, print the taskId

Then read what the agent did:  python s53_read_investigation.py <taskId>

IAM: aidevops:CreateBacklogTask, aidevops:GetBacklogTask
"""
import argparse
import time
import uuid

from common import client, space_id

# Final states: stop polling.
DONE = {"COMPLETED", "FAILED", "TIMED_OUT", "CANCELED", "LINKED", "SKIPPED"}
# Needs a person: the agent proposed a mitigation and waits for approval in the web app.
NEEDS_YOU = {"PENDING_CUSTOMER_APPROVAL"}


def start_investigation(title, description, priority="HIGH"):
    """Create an INVESTIGATION task. Returns the task dict.

    create_backlog_task parameters:
      taskType     "INVESTIGATION" for incident root cause analysis.
                   (Also: "EVALUATION" for prevention, see 5.5;
                   "RELEASE_READINESS_REVIEW", "RELEASE_TESTING".)
      title        Short, shown in the web app and used by triage to spot duplicates.
      description  The more concrete the better: when it started, what you see,
                   which service, how big the impact. The agent starts from this text.
      priority     CRITICAL | HIGH | MEDIUM | LOW | MINIMAL
      clientToken  Idempotency key. If a network retry sends the same token again,
                   the service returns the same task instead of starting a second one.
    """
    return client.create_backlog_task(
        agentSpaceId=space_id(),
        taskType="INVESTIGATION",
        title=title,
        description=description,
        priority=priority,
        clientToken=str(uuid.uuid4()),
    )["task"]


def wait_for(task_id, poll_seconds=30, max_wait_seconds=3600, log=print):
    """Poll get_backlog_task until the task is done or needs a person.

    Status flow: PENDING_TRIAGE -> PENDING_START -> IN_PROGRESS (-> WAITING) -> COMPLETED.
    Triage can end it early: LINKED (merged into an existing investigation,
    see primaryTaskId) or SKIPPED (filtered out, see statusReason).
    """
    deadline = time.monotonic() + max_wait_seconds
    while True:
        task = client.get_backlog_task(agentSpaceId=space_id(), taskId=task_id)["task"]
        log(f"  {time.strftime('%H:%M:%S')} status = {task['status']}")
        if task["status"] in DONE | NEEDS_YOU:
            return task
        if time.monotonic() > deadline:
            log("  stop waiting; the task keeps running on the service side")
            return task
        time.sleep(poll_seconds)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("title")
    p.add_argument("description")
    p.add_argument("--priority", default="HIGH", choices=["CRITICAL", "HIGH", "MEDIUM", "LOW", "MINIMAL"])
    p.add_argument("--no-wait", action="store_true")
    a = p.parse_args()

    task = start_investigation(a.title, a.description, a.priority)
    print(f"taskId {task['taskId']}  status {task['status']}")
    if not a.no_wait:
        task = wait_for(task["taskId"])
        if task["status"] == "LINKED":
            print(f"merged into {task.get('primaryTaskId')}: {task.get('statusReason', '')}")
        elif task["status"] in NEEDS_YOU:
            print("approve or reject the mitigation plan in the Agent Space web app")
        elif task.get("statusReason"):
            print(f"reason: {task['statusReason']}")
    print(f"next: python s53_read_investigation.py {task['taskId']}")
