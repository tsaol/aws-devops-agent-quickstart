"""5.1 Client and pagination: shared helpers for every example.

  python common.py            # list Agent Spaces in the Region and check AGENT_SPACE_ID

Env: AGENT_SPACE_ID, AWS_REGION (else AWS_DEFAULT_REGION, else us-east-1)
IAM: aidevops:ListAgentSpaces, aidevops:GetAgentSpace
"""
import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def make_client(region=REGION):
    """Create the DevOps Agent client.

    - Service name is "devops-agent" (needs boto3 >= 1.43 for the full API).
    - The Region must be the Agent Space's Region, not the Region of the resources
      you investigate: one Agent Space can look at every Region of its accounts.
    - read_timeout: SendMessage streams for a while, so the 60 s default is too short.
    - retries "adaptive": backs off on ThrottlingException by itself.
    """
    return boto3.client(
        "devops-agent",
        region_name=region,
        config=Config(read_timeout=300, retries={"max_attempts": 8, "mode": "adaptive"}),
    )


client = make_client()


def space_id():
    """AGENT_SPACE_ID from the environment, or exit with a hint."""
    sid = os.environ.get("AGENT_SPACE_ID")
    if not sid:
        sys.exit("set AGENT_SPACE_ID (run `python common.py` to list Agent Spaces)")
    return sid


def pages(operation, key, **params):
    """Yield every item of a list call, page by page.

    boto3 has paginators for list_agent_spaces, list_backlog_tasks, list_executions,
    list_journal_records, list_goals, list_triggers, list_assets and a few more.
    list_recommendations and list_chats have none: they only return nextToken,
    so we loop by hand.
    """
    if client.can_paginate(operation):
        yield from client.get_paginator(operation).paginate(**params).search(f"{key}[]")
        return
    token = None
    while True:
        page = getattr(client, operation)(**params, **({"nextToken": token} if token else {}))
        yield from page.get(key, [])
        token = page.get("nextToken")
        if not token:
            return


def error_code(e):
    """Short 'Code: message' for a ClientError (AccessDenied, Validation, Throttling...)."""
    if isinstance(e, ClientError):
        err = e.response.get("Error", {})
        return f"{err.get('Code')}: {err.get('Message')}"
    return f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    print(f"Region {REGION}")
    for s in pages("list_agent_spaces", "agentSpaces"):
        print(f"  {s['agentSpaceId']}  {s.get('name')}")
    sid = os.environ.get("AGENT_SPACE_ID")
    if sid:
        try:
            space = client.get_agent_space(agentSpaceId=sid)["agentSpace"]
            print(f"AGENT_SPACE_ID ok: {space.get('name')} (created {space.get('createdAt'):%Y-%m-%d})")
        except ClientError as e:
            sys.exit(f"AGENT_SPACE_ID {sid}: {error_code(e)}")
