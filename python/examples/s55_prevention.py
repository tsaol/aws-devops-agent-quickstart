"""5.5 Prevention: goals, evaluations and recommendations.

The agent looks back at recent investigations and proposes lasting fixes
(observability, infrastructure, governance, code). This runs as an EVALUATION task,
weekly by default, tied to a goal of the Agent Space.

  python s55_prevention.py goals                          # goals and their evaluation schedule
  python s55_prevention.py evaluate [--goal <goalId>] [--no-wait]   # run an evaluation now
  python s55_prevention.py list [--status PROPOSED] [--task <taskId>] [--goal <goalId>]
  python s55_prevention.py show <recommendationId>
  python s55_prevention.py keep|discard|done <recommendationId> [--why "reason"]
  python s55_prevention.py schedule on|off [--goal <goalId>]

IAM: aidevops:ListGoals, aidevops:UpdateGoal, aidevops:CreateBacklogTask, aidevops:GetBacklogTask,
     aidevops:ListRecommendations, aidevops:GetRecommendation, aidevops:UpdateRecommendation
"""
import argparse
import json
import sys
import uuid

from common import client, pages, space_id
from s52_start_investigation import wait_for

# Web app button -> API status. The docs do not spell out this mapping; it follows the names.
ACTION = {"keep": "ACCEPTED", "discard": "REJECTED", "done": "COMPLETED"}


def goals():
    """list_goals: each goal has a type, a status, and evaluationSchedule {state, expression}.
    ONCALL_REPORT is the built-in weekly prevention review. CUSTOMER_DEFINED goals include
    the schedule triggers of custom agents (5.6): their goalId equals the triggerId."""
    return list(pages("list_goals", "goals", agentSpaceId=space_id()))


def run_evaluation(goal_id=None, wait=True):
    """Start an evaluation now: create_backlog_task with taskType="EVALUATION".

    The description must be a JSON document with the goal to evaluate:
        {"goal_id": "goal-..."}
    Plain text fails with "Evaluation task must have a json description containing
    valid goal_id". Only one evaluation runs at a time per Agent Space (fixed quota).
    Recommendations it creates or updates carry its taskId.
    """
    goal_id = goal_id or default_goal()
    task = client.create_backlog_task(
        agentSpaceId=space_id(), taskType="EVALUATION", priority="LOW",
        title="On-demand evaluation from s55_prevention.py",
        description=json.dumps({"goal_id": goal_id}),
        clientToken=str(uuid.uuid4()),
    )["task"]
    print(f"evaluation task {task['taskId']} for {goal_id}  status {task['status']}")
    return wait_for(task["taskId"], poll_seconds=60, max_wait_seconds=3 * 3600) if wait else task


def recommendations(status=None, task_id=None, goal_id=None):
    """list_recommendations, best first.

    Filters: status (PROPOSED, ACCEPTED, REJECTED, CLOSED, COMPLETED, UPDATE_IN_PROGRESS),
    priority (HIGH, MEDIUM, LOW), taskId, goalId. No boto3 paginator: common.pages()
    follows nextToken. rankPosition (1 = most important) is set for proposed/kept ones.
    """
    params = {"agentSpaceId": space_id()}
    for k, v in (("status", status), ("taskId", task_id), ("goalId", goal_id)):
        if v:
            params[k] = v
    recs = list(pages("list_recommendations", "recommendations", **params))
    return sorted(recs, key=lambda r: (r.get("rankPosition") or 10**6, r["priority"]))


# content.summary is a JSON string with these sections (seen in real responses):
SECTIONS = [("overview", "概述"), ("background", "背景"), ("next_steps", "下一步"),
            ("considerations", "注意"), ("affected_incidents", "相关事故")]


def parse_summary(rec):
    """Return content.summary as a dict. Falls back to {"overview": text} if it is plain text."""
    text = rec["content"].get("summary") or ""
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"overview": text}
    except ValueError:
        return {"overview": text}


def set_status(rec_id, status, why=None):
    """update_recommendation. additionalContext is your reason in plain words;
    the agent uses discard reasons to shape later recommendations."""
    params = dict(agentSpaceId=space_id(), recommendationId=rec_id, status=status,
                  clientToken=str(uuid.uuid4()))
    if why:
        params["additionalContext"] = why
    return client.update_recommendation(**params)["recommendation"]


def default_goal():
    """The built-in prevention goal is the ONCALL_REPORT one. Do not just take goals()[0]:
    every schedule trigger (5.6) also shows up in list_goals as a CUSTOMER_DEFINED goal."""
    gs = [g for g in goals() if g["goalType"] == "ONCALL_REPORT"] or goals()
    return gs[0]["goalId"]


def set_schedule(enabled, goal_id=None):
    """update_goal can switch the evaluation schedule on or off. It cannot change the
    expression (rate(7 days) by default)."""
    goal_id = goal_id or default_goal()
    g = client.update_goal(agentSpaceId=space_id(), goalId=goal_id,
                           evaluationSchedule={"state": "ENABLED" if enabled else "DISABLED"},
                           clientToken=str(uuid.uuid4()))["goal"]
    return g


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("goals")
    e = sub.add_parser("evaluate"); e.add_argument("--no-wait", action="store_true"); e.add_argument("--goal")
    l = sub.add_parser("list")
    l.add_argument("--status"); l.add_argument("--task"); l.add_argument("--goal")
    s = sub.add_parser("show"); s.add_argument("rec_id")
    for name in ACTION:
        x = sub.add_parser(name); x.add_argument("rec_id"); x.add_argument("--why")
    sc = sub.add_parser("schedule"); sc.add_argument("state", choices=["on", "off"]); sc.add_argument("--goal")
    a = p.parse_args()

    if a.cmd == "goals":
        for g in goals():
            sch = g.get("evaluationSchedule") or {}
            print(f"{g['goalId']}  {g['goalType']}  {g['status']}  schedule {sch.get('state')} {sch.get('expression', '')}")
            print(f"  {g['title']}\n  last evaluation task: {g.get('lastTaskId')}")
    elif a.cmd == "evaluate":
        t = run_evaluation(a.goal, wait=not a.no_wait)
        print(f"next: python s55_prevention.py list --task {t['taskId']}")
    elif a.cmd == "list":
        recs = recommendations(a.status, a.task, a.goal)
        for r in recs:
            rank = f"#{r['rankPosition']}" if r.get("rankPosition") else "  -"
            cat = parse_summary(r).get("category", "")
            print(f"{rank:>4} [{r['priority']:6}] {r['status']:18} {r['recommendationId']}  {cat}\n       {r['title']}")
        print(f"{len(recs)} recommendations")
    elif a.cmd == "show":
        r = client.get_recommendation(agentSpaceId=space_id(), recommendationId=a.rec_id)["recommendation"]
        info = parse_summary(r)
        print(f"{r['title']}\n[{r['priority']}] {r['status']}  {info.get('category', '')}  "
              f"version {r['version']}  task {r['taskId']}")
        for key, label in SECTIONS:
            if info.get(key):
                v = info[key]
                print(f"\n{label}:\n  {', '.join(v) if isinstance(v, list) else v}")
        if r["content"].get("spec"):
            print("\n--- spec ---\n" + r["content"]["spec"])
    elif a.cmd in ACTION:
        r = set_status(a.rec_id, ACTION[a.cmd], a.why)
        print(f"{r['recommendationId']} -> {r['status']}")
    elif a.cmd == "schedule":
        g = set_schedule(a.state == "on", a.goal)
        print(f"{g['goalId']} schedule {g['evaluationSchedule']['state']} {g['evaluationSchedule'].get('expression', '')}")
    sys.exit(0)
