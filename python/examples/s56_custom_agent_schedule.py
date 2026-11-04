"""5.6 Create a custom agent and run it on a schedule.

A custom agent is an asset (assetType "custom_agent") with a system prompt in AGENT.md,
plus optional skills, tools and memory stores. A schedule trigger runs it automatically.

  python s56_custom_agent_schedule.py create weekly-health --prompt-file prompt.md [--skill aws-health-events]
  python s56_custom_agent_schedule.py agents
  python s56_custom_agent_schedule.py schedule <agentAssetId> "cron(0 1 ? * MON *)" [--prompt "本周重点看告警"] [--inactive]
  python s56_custom_agent_schedule.py triggers
  python s56_custom_agent_schedule.py pause|resume <triggerId>
  python s56_custom_agent_schedule.py delete-trigger <triggerId>
  python s56_custom_agent_schedule.py delete-agent <agentAssetId>

IAM: aidevops:CreateAsset, aidevops:ListAssets, aidevops:DeleteAsset,
     aidevops:CreateTrigger, aidevops:ListTriggers, aidevops:GetTrigger,
     aidevops:UpdateTrigger, aidevops:DeleteTrigger
"""
import argparse
import pathlib

from common import client, pages, space_id


def create_agent(name, system_prompt, skill_names=()):
    """create_asset(assetType="custom_agent").

    metadata:
      name    required; lowercase letters, numbers and hyphens, 1-64 chars
      skills  optional; skill **assetIds** (not names) of skills already in the Agent Space
      tools / memory_stores  optional; MCP tools are usually added later through Chat
    content: the system prompt as a text file named AGENT.md (up to 1.5 MB).
    """
    sid = space_id()
    skill_ids = []
    if skill_names:
        installed = {a["metadata"].get("name"): a["assetId"]
                     for a in pages("list_assets", "items", agentSpaceId=sid, assetType="skill")}
        missing = [s for s in skill_names if s not in installed]
        if missing:
            raise SystemExit(f"install these skills first: {', '.join(missing)}")
        skill_ids = [installed[s] for s in skill_names]
    return client.create_asset(
        agentSpaceId=sid,
        assetType="custom_agent",
        metadata={"name": name, "skills": skill_ids},
        content={"file": {"path": "AGENT.md", "body": {"text": system_prompt}}},
    )["asset"]


def schedule(agent_asset_id, expression, prompt=None, active=True):
    """create_trigger(type="TIME_BASED").

    condition.schedule.expression  EventBridge syntax, UTC:
        rate(1 hour) | rate(7 days) | cron(0 1 ? * MON *) (one of day-of-month /
        day-of-week must be "?")
    action  a JSON document; the shape the service expects is
        {"actionType": "create:task", "task": {"agent": "custom:<assetId>", "description": "<prompt>"}}
        task.description is the optional user prompt for each run. Unknown keys are
        dropped without an error, so check get_trigger if a field seems to be ignored.
    status  "Active" or "Inactive" (paused). Type, condition and action cannot be
        changed later: delete and create again.
    """
    task = {"agent": f"custom:{agent_asset_id}"}
    if prompt:
        task["description"] = prompt
    return client.create_trigger(
        agentSpaceId=space_id(),
        type="TIME_BASED",
        condition={"schedule": {"expression": expression}},
        action={"actionType": "create:task", "task": task},
        status="Active" if active else "Inactive",
    )["trigger"]


def show_trigger(t):
    task = t["action"].get("task", {})
    prompt = f'  prompt "{task["description"]}"' if task.get("description") else ""
    return f"{t['triggerId']}  {t['status']:8}  {t['condition']['schedule']['expression']:22} {task.get('agent')}{prompt}"


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("name")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--prompt"); g.add_argument("--prompt-file")
    c.add_argument("--skill", action="append", default=[])
    sub.add_parser("agents")
    s = sub.add_parser("schedule"); s.add_argument("agent_id"); s.add_argument("expression")
    s.add_argument("--prompt"); s.add_argument("--inactive", action="store_true")
    sub.add_parser("triggers")
    for name in ("pause", "resume", "delete-trigger"):
        x = sub.add_parser(name); x.add_argument("trigger_id")
    d = sub.add_parser("delete-agent"); d.add_argument("agent_id")
    a = p.parse_args()
    sid = space_id()

    if a.cmd == "create":
        text = a.prompt or pathlib.Path(a.prompt_file).read_text(encoding="utf-8")
        asset = create_agent(a.name, text, a.skill)
        print(f"custom agent {asset['assetId']}  {asset['metadata']['name']}")
        print(f'next: python s56_custom_agent_schedule.py schedule {asset["assetId"]} "rate(7 days)"')
    elif a.cmd == "agents":
        for x in pages("list_assets", "items", agentSpaceId=sid, assetType="custom_agent"):
            m = x["metadata"]
            print(f"{x['assetId']}  {m.get('name')}  skills {len(m.get('skills', []))}  tools {len(m.get('tools', []))}")
    elif a.cmd == "schedule":
        print(show_trigger(schedule(a.agent_id, a.expression, a.prompt, active=not a.inactive)))
    elif a.cmd == "triggers":
        for t in pages("list_triggers", "items", agentSpaceId=sid):
            print(show_trigger(t))
    elif a.cmd in ("pause", "resume"):
        t = client.update_trigger(agentSpaceId=sid, triggerId=a.trigger_id,
                                  status="Inactive" if a.cmd == "pause" else "Active")["trigger"]
        print(show_trigger(t))
    elif a.cmd == "delete-trigger":
        client.delete_trigger(agentSpaceId=sid, triggerId=a.trigger_id)
        print(f"deleted trigger {a.trigger_id}")
    elif a.cmd == "delete-agent":
        client.delete_asset(agentSpaceId=sid, assetId=a.agent_id)
        print(f"deleted custom agent {a.agent_id}")
