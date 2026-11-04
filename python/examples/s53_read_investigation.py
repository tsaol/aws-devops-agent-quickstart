"""5.3 Read what the agent did in an investigation.

  python s53_read_investigation.py <taskId>                  # timeline of findings + conclusion
  python s53_read_investigation.py <taskId> --types          # how many records of each type
  python s53_read_investigation.py <taskId> --only investigation_result

IAM: aidevops:GetBacklogTask, aidevops:ListExecutions, aidevops:ListJournalRecords,
     aidevops:ListRecommendations
"""
import argparse
import collections
import datetime as dt
import json

from common import client, pages, space_id

# Record types a person wants to read: type -> (title field, body field).
# Other types are model traffic or web UI data: message, utilization, ui_investigation_summary.
SHOW = {
    "observation": ("title", "analysis"),          # a finding
    "investigation_gap": ("title", "description"),  # something the agent could not check
    "root_cause": ("title", "description"),
    "mitigation": ("title", "description"),
    "investigation_result": (None, "text"),         # the conclusion, usually the last record
}


def parse_content(record):
    """`content` is a JSON string most of the time; sometimes already a dict."""
    c = record["content"]
    if isinstance(c, str):
        try:
            data = json.loads(c)
        except ValueError:
            return {"text": c}
        return data if isinstance(data, dict) else {"text": c}
    return c if isinstance(c, dict) else {"text": str(c)}


def journal(task_id, record_type=None):
    """Yield (execution, record) for every journal record of a task, oldest first.

    A task has one or more executions (agentSubTask tells which agent ran it, e.g. "oncall";
    parentExecutionId links sub-executions). Each execution has its own journal.

    list_journal_records parameters:
      order       "ASC" = oldest first. The conclusion comes last, so read every page:
                  one page holds at most 100 records.
      recordType  optional server-side filter, e.g. "investigation_result".
    """
    sid = space_id()
    for ex in pages("list_executions", "executions", agentSpaceId=sid, taskId=task_id):
        params = dict(agentSpaceId=sid, executionId=ex["executionId"], order="ASC")
        if record_type:
            params["recordType"] = record_type
        for r in pages("list_journal_records", "records", **params):
            yield ex, r


def line(record):
    """One readable line for a record, or None for record types nobody reads."""
    kind = record["recordType"]
    if kind not in SHOW:
        return None
    c = parse_content(record)
    title_key, body_key = SHOW[kind]
    title = c.get(title_key) if title_key else None
    body = c.get(body_key) or ""
    return f"{kind}: {title} - {body}" if title else f"{kind}: {body}"


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("task_id")
    p.add_argument("--types", action="store_true", help="count records per type")
    p.add_argument("--only", help="server-side recordType filter, e.g. investigation_result")
    a = p.parse_args()

    task = client.get_backlog_task(agentSpaceId=space_id(), taskId=a.task_id)["task"]
    print(f"{task['title']}  [{task['status']}]")

    if a.types:
        counts = collections.Counter(r["recordType"] for _, r in journal(a.task_id, a.only))
        for kind, n in counts.most_common():
            print(f"  {n:4}  {kind}{'' if kind in SHOW else '   (not shown by default)'}")
    else:
        current = None
        for ex, r in journal(a.task_id, a.only):
            if ex["executionId"] != current:
                current = ex["executionId"]
                print(f"\n== execution {current} ({ex['agentSubTask']}, {ex['executionStatus']})")
            text = line(r)
            if text:
                # botocore returns local-time datetimes; print UTC so every machine agrees
                print(f"  [{r['createdAt'].astimezone(dt.timezone.utc):%H:%M:%S} UTC] {text}")

        recs = list(pages("list_recommendations", "recommendations",
                          agentSpaceId=space_id(), taskId=a.task_id))
        for rec in recs:
            print(f"\n* [{rec['priority']}] {rec['title']}\n  {rec['content']['summary']}")
