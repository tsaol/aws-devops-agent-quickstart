"""Offline tests for python/examples/ (section 5 of docs/boto3-examples.md).

Stubber checks each request against the real devops-agent API model, so a wrong
operation name, a missing required field or a bad enum value fails here.

  python tests/test_examples.py
"""
import datetime as dt
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent          # python/
EX = HERE / "examples"
ROOT = HERE.parent
os.environ["AGENT_SPACE_ID"] = "00000000-0000-0000-0000-000000000000"
os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
sys.path.insert(0, str(EX))

from botocore.stub import ANY, Stubber  # noqa: E402

import common  # noqa: E402
import s53_read_investigation as s53  # noqa: E402
import s54_chat_stream as s54  # noqa: E402
import s55_prevention as s55  # noqa: E402
import s56_custom_agent_schedule as s56  # noqa: E402

S = os.environ["AGENT_SPACE_ID"]
NOW = dt.datetime(2026, 11, 4, 14, 5, tzinfo=dt.timezone.utc)
GOAL = "goal-00000000-0000-4000-8000-000000000001"


def quiet(fn, *a, **kw):
    with redirect_stdout(io.StringIO()) as out:
        r = fn(*a, **kw)
    return r, out.getvalue()


def test_doc_code_matches_scripts():
    doc = (ROOT / "docs" / "boto3-examples.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)\n```", doc, re.S)
    sources = "\n".join(p.read_text(encoding="utf-8") for p in EX.glob("*.py"))
    missing = [b.splitlines()[0] for b in blocks if b not in sources]
    assert blocks and not missing, missing
    print(f"ok  doc: all {len(blocks)} Python blocks in docs/boto3-examples.md are copied from python/examples/")


def goal(gid, gtype):
    return {"agentSpaceArn": "arn:aws:aidevops:us-east-1:111122223333:agentspace/" + S, "goalId": gid,
            "title": "t", "content": {"description": "d", "objectives": "o"}, "status": "ACTIVE",
            "goalType": gtype, "createdAt": NOW, "updatedAt": NOW, "version": 1,
            "evaluationSchedule": {"state": "ENABLED", "expression": "rate(7 days)"}}


def rec(rid, rank, summary):
    return {"agentSpaceArn": "arn:aws:aidevops:us-east-1:111122223333:agentspace/" + S, "recommendationId": rid,
            "taskId": "t-1", "title": rid, "content": {"summary": summary}, "status": "PROPOSED",
            "priority": "MEDIUM", "createdAt": NOW, "updatedAt": NOW, "version": 1,
            **({"rankPosition": rank} if rank else {})}


def test_pages_paginator_and_manual():
    st = Stubber(common.client)
    st.add_response("list_executions", {"executions": [{"agentSpaceId": S, "executionId": "e-1", "agentSubTask": "oncall",
                    "createdAt": NOW, "updatedAt": NOW, "executionStatus": "STOPPED"}], "nextToken": "n2"},
                    {"agentSpaceId": S, "taskId": "t-1"})
    st.add_response("list_executions", {"executions": [{"agentSpaceId": S, "executionId": "e-2", "agentSubTask": "oncall",
                    "createdAt": NOW, "updatedAt": NOW, "executionStatus": "STOPPED"}]},
                    {"agentSpaceId": S, "taskId": "t-1", "nextToken": "n2"})
    st.add_response("list_recommendations", {"recommendations": [rec("r-1", None, "{}")], "nextToken": "p2"},
                    {"agentSpaceId": S})
    st.add_response("list_recommendations", {"recommendations": [rec("r-2", None, "{}")]},
                    {"agentSpaceId": S, "nextToken": "p2"})
    with st:
        ex = [e["executionId"] for e in common.pages("list_executions", "executions", agentSpaceId=S, taskId="t-1")]
        rs = [r["recommendationId"] for r in common.pages("list_recommendations", "recommendations", agentSpaceId=S)]
        st.assert_no_pending_responses()
    assert ex == ["e-1", "e-2"] and rs == ["r-1", "r-2"], (ex, rs)
    print("ok  5.1 pages(): boto3 paginator (list_executions) and manual nextToken (list_recommendations)")


def test_journal_lines():
    obs = {"recordType": "observation", "content": '{"title": "无告警", "analysis": "0 个"}'}
    res = {"recordType": "investigation_result", "content": '{"text": "结论"}'}
    assert s53.line(obs) == "observation: 无告警 - 0 个"
    assert s53.line(res) == "investigation_result: 结论"
    assert s53.line({"recordType": "utilization", "content": "{}"}) is None
    assert s53.parse_content({"content": "not json"}) == {"text": "not json"}
    assert s53.parse_content({"content": "[1]"}) == {"text": "[1]"}
    print("ok  5.3 journal: JSON content parsed, noise hidden, odd content does not crash")


def test_chat_blocks():
    def fake(**kw):
        assert kw == {"agentSpaceId": S, "executionId": "c" * 32, "content": "q"}, kw
        return {"events": iter([
            {"contentBlockStart": {"index": 0, "type": "thinking"}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": "hmm"}}}},
            {"contentBlockStart": {"index": 1, "type": "tool_summary"}},
            {"contentBlockDelta": {"index": 1, "delta": {"jsonDelta": {"partialJson": "{}"}}}},
            {"contentBlockStart": {"index": 2, "type": "text"}},
            {"contentBlockDelta": {"index": 2, "delta": {"textDelta": {"text": "27"}}}},
            {"contentBlockStart": {"index": 3, "type": "final_response"}},
            {"contentBlockDelta": {"index": 3, "delta": {"textDelta": {"text": "27"}}}},
            {"responseCompleted": {"responseId": "x", "usage": {"inputTokens": 6, "outputTokens": 9}}},
        ])}
    real, s54.client.send_message = s54.client.send_message, fake
    try:
        (answer, usage), out = quiet(s54.send, "c" * 32, "q")
    finally:
        s54.client.send_message = real
    assert answer == "27" and out == "27\n" and usage["outputTokens"] == 9, (answer, out, usage)
    print("ok  5.4 send(): only the text block is printed, usage read from responseCompleted")


def test_evaluation_request_and_default_goal():
    st = Stubber(common.client)
    # a trigger goal comes first; default_goal() must pick the ONCALL_REPORT one
    st.add_response("list_goals", {"goals": [goal("goal-trigger", "CUSTOMER_DEFINED"), goal(GOAL, "ONCALL_REPORT")]},
                    {"agentSpaceId": S})
    st.add_response("create_backlog_task", {"task": {"agentSpaceId": S, "taskId": "t-9", "title": "x",
                    "taskType": "EVALUATION", "priority": "LOW", "status": "PENDING_START",
                    "createdAt": NOW, "updatedAt": NOW, "version": 1}},
                    {"agentSpaceId": S, "taskType": "EVALUATION", "priority": "LOW", "title": ANY,
                     "description": json.dumps({"goal_id": GOAL}), "clientToken": ANY})
    with st:
        t, out = quiet(s55.run_evaluation, wait=False)
        st.assert_no_pending_responses()
    assert t["taskId"] == "t-9" and GOAL in out, out
    print("ok  5.5 evaluate: description is {\"goal_id\": ...}; default goal skips trigger goals")


def test_recommendation_summary_and_order():
    full = json.dumps({"title": "x", "category": "MONITORING_AND_OBSERVABILITY", "overview": "o",
                       "next_steps": "n", "affected_incidents": ["i-1"]})
    assert s55.parse_summary({"content": {"summary": full}})["category"] == "MONITORING_AND_OBSERVABILITY"
    assert s55.parse_summary({"content": {"summary": "plain text"}}) == {"overview": "plain text"}
    st = Stubber(common.client)
    st.add_response("list_recommendations", {"recommendations": [rec("r-unranked", None, full), rec("r-2", 2, full),
                    rec("r-1", 1, full)]}, {"agentSpaceId": S, "status": "PROPOSED"})
    st.add_response("update_recommendation", {"recommendation": {**rec("r-1", 1, full), "status": "REJECTED"}},
                    {"agentSpaceId": S, "recommendationId": "r-1", "status": "REJECTED",
                     "additionalContext": "we use Datadog", "clientToken": ANY})
    with st:
        order = [r["recommendationId"] for r in s55.recommendations(status="PROPOSED")]
        r = s55.set_status("r-1", s55.ACTION["discard"], "we use Datadog")
        st.assert_no_pending_responses()
    assert order == ["r-1", "r-2", "r-unranked"] and r["status"] == "REJECTED", order
    print("ok  5.5 recommendations: summary JSON parsed, sorted by rank, discard sends REJECTED + reason")


def test_custom_agent_and_trigger_requests():
    st = Stubber(common.client)
    asset = lambda aid, name: {"assetId": aid, "assetType": "x", "metadata": {"name": name}, "version": 1,  # noqa: E731
                               "createdAt": NOW, "updatedAt": NOW}
    st.add_response("list_assets", {"items": [asset("ki-skill-1", "aws-health-events")]},
                    {"agentSpaceId": S, "assetType": "skill"})
    st.add_response("create_asset", {"asset": asset("ki-agent-1", "weekly-health")}, {
        "agentSpaceId": S, "assetType": "custom_agent",
        "metadata": {"name": "weekly-health", "skills": ["ki-skill-1"]},      # assetId, not the name
        "content": {"file": {"path": "AGENT.md", "body": {"text": "# prompt"}}}})
    trig = {"triggerId": "goal-t1", "agentSpaceId": S, "type": "TIME_BASED",
            "condition": {"schedule": {"expression": "rate(7 days)"}},
            "action": {"actionType": "create:task", "task": {"agent": "custom:ki-agent-1", "description": "看告警"}},
            "status": "Inactive", "createdAt": NOW, "updatedAt": NOW}
    st.add_response("create_trigger", {"trigger": trig}, {
        "agentSpaceId": S, "type": "TIME_BASED", "condition": {"schedule": {"expression": "rate(7 days)"}},
        "action": {"actionType": "create:task", "task": {"agent": "custom:ki-agent-1", "description": "看告警"}},
        "status": "Inactive"})
    with st:
        a = s56.create_agent("weekly-health", "# prompt", ["aws-health-events"])
        t = s56.schedule(a["assetId"], "rate(7 days)", prompt="看告警", active=False)
        st.assert_no_pending_responses()
    assert 'prompt "看告警"' in s56.show_trigger(t)
    st = Stubber(common.client)
    st.add_response("list_assets", {"items": []}, {"agentSpaceId": S, "assetType": "skill"})
    with st:
        try:
            s56.create_agent("x", "p", ["not-installed"])
            raise AssertionError("expected SystemExit")
        except SystemExit as e:
            assert "install these skills first" in str(e)
    print("ok  5.6 custom agent: skills by assetId, AGENT.md prompt; trigger action custom:<id> + task.description")


if __name__ == "__main__":
    test_doc_code_matches_scripts()
    test_pages_paginator_and_manual()
    test_journal_lines()
    test_chat_blocks()
    test_evaluation_request_and_default_goal()
    test_recommendation_summary_and_order()
    test_custom_agent_and_trigger_requests()
    print("ALL OK")
