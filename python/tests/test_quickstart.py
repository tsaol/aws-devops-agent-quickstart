"""Offline tests for devops_agent_quickstart.py.

Stubber checks every request against the real devops-agent API model,
so wrong names, missing required params, or bad enum values fail here.
Runs with TZ=Asia/Shanghai to check that times are printed in UTC.
"""
import datetime as dt
import io
import os
import sys
import time
from contextlib import redirect_stdout

os.environ["TZ"] = "Asia/Shanghai"
time.tzset()
os.environ["AGENT_SPACE_ID"] = "00000000-0000-0000-0000-000000000000"
os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botocore.stub import Stubber  # noqa: E402
from botocore.validate import validate_parameters  # noqa: E402

import devops_agent_quickstart as q  # noqa: E402

S = os.environ["AGENT_SPACE_ID"]
EX = "e0000000-0000-4000-8000-000000000001"
CHAT = "c0000000-0000-4000-8000-000000000001"
NOW = dt.datetime(2026, 11, 4, 14, 5, tzinfo=dt.timezone.utc)


def task(status, **extra):
    t = {"agentSpaceId": S, "taskId": "t-1", "title": "5xx spike", "taskType": "INVESTIGATION",
         "priority": "HIGH", "status": status, "createdAt": NOW, "updatedAt": NOW, "version": 1, **extra}
    return {"task": t}


def rec(rid, kind, content):
    return {"agentSpaceId": S, "executionId": EX, "recordId": rid, "createdAt": NOW,
            "recordType": kind, "content": content}


def recommendation(rid, title):
    return {"agentSpaceArn": "arn:aws:aidevops:us-east-1:111122223333:agentspace/" + S,
            "recommendationId": rid, "taskId": "t-1", "title": title,
            "content": {"summary": title + " summary"}, "status": "PROPOSED",
            "priority": "HIGH", "createdAt": NOW, "updatedAt": NOW, "version": 1}


def run(fn, *a, **kw):
    out = io.StringIO()
    with redirect_stdout(out):
        r = fn(*a, **kw)
    return r, out.getvalue()


def test_investigate_full_flow_with_pagination():
    st = Stubber(q.client)
    st.add_response("create_backlog_task", task("PENDING_START"), {
        "agentSpaceId": S, "taskType": "INVESTIGATION", "title": "5xx spike",
        "description": "ALB 5xx > 5%", "priority": "HIGH"})
    for status in ("WAITING", "IN_PROGRESS", "COMPLETED"):
        st.add_response("get_backlog_task", task(status), {"agentSpaceId": S, "taskId": "t-1"})
    st.add_response("list_executions", {"executions": [{
        "agentSpaceId": S, "executionId": EX, "agentSubTask": "oncall",
        "createdAt": NOW, "updatedAt": NOW, "executionStatus": "STOPPED"}]},
        {"agentSpaceId": S, "taskId": "t-1"})
    # journal: two pages, the conclusion is on the second page
    st.add_response("list_journal_records", {"records": [
        rec("r-1", "observation", '{"title": "SG 规则被删", "analysis": "ALB lost port 443"}'),
        rec("r-2", "utilization", '{"data": {"context_window": {"utilization": 1.8}}}'),
    ], "nextToken": "j2"}, {"agentSpaceId": S, "executionId": EX, "order": "ASC"})
    st.add_response("list_journal_records", {"records": [
        rec("r-3", "investigation_result", '{"text": "根因：443 端口规则被删除"}'),
    ]}, {"agentSpaceId": S, "executionId": EX, "order": "ASC", "nextToken": "j2"})
    # recommendations: two pages
    st.add_response("list_recommendations", {"recommendations": [recommendation("rec-1", "Restore SG rule")],
                                             "nextToken": "r2"}, {"agentSpaceId": S, "taskId": "t-1"})
    st.add_response("list_recommendations", {"recommendations": [recommendation("rec-2", "Add an alarm")]},
                    {"agentSpaceId": S, "taskId": "t-1", "nextToken": "r2"})
    with st:
        t, out = run(q.investigate, "5xx spike", "ALB 5xx > 5%", poll_seconds=0)
        st.assert_no_pending_responses()
    assert t["status"] == "COMPLETED", t
    assert "status = WAITING" in out, out
    assert "[14:05:00] observation: SG 规则被删 - ALB lost port 443" in out, out  # UTC, not 22:05
    assert "[14:05:00] investigation_result: 根因：443 端口规则被删除" in out, out  # page 2
    assert "utilization" not in out, out
    assert "Restore SG rule" in out and "Add an alarm" in out, out
    print("ok  investigate: polls, paginates journal + recommendations, UTC times, hides noise")


def _short_flow(final_status, **extra):
    st = Stubber(q.client)
    st.add_response("create_backlog_task", task("PENDING_START"))
    st.add_response("get_backlog_task", task(final_status, **extra))
    st.add_response("list_executions", {"executions": []})
    st.add_response("list_recommendations", {"recommendations": []})
    return st


def test_needs_approval_and_linked():
    st = _short_flow("PENDING_CUSTOMER_APPROVAL")
    with st:
        t, out = run(q.investigate, "x", "y", poll_seconds=0)
    assert t["status"] == "PENDING_CUSTOMER_APPROVAL" and "approval" in out, out
    st = _short_flow("LINKED", primaryTaskId="t-0", statusReason="same alarm as t-0")
    with st:
        t, out = run(q.investigate, "x", "y", poll_seconds=0)
    assert "merged into task t-0: same alarm as t-0" in out, out
    print("ok  investigate: stops on PENDING_CUSTOMER_APPROVAL, prints the primary task for LINKED")


def test_timeout():
    st = Stubber(q.client)
    st.add_response("create_backlog_task", task("PENDING_START"))
    st.add_response("list_executions", {"executions": []})
    st.add_response("list_recommendations", {"recommendations": []})
    with st:
        t, out = run(q.investigate, "x", "y", poll_seconds=0, max_wait_seconds=-1)
    assert t["status"] == "PENDING_START" and "stop waiting" in out, out
    print("ok  investigate: stops waiting after MAX_WAIT_MINUTES")


def test_record_text_edge_cases():
    assert q.record_text({"recordType": "message", "content": "{}"}) is None
    assert q.record_text({"recordType": "investigation_result", "content": "not json"}) == "investigation_result: not json"
    assert q.record_text({"recordType": "investigation_result", "content": "[1, 2]"}) == "investigation_result: [1, 2]"
    assert q.record_text({"recordType": "observation", "content": {"title": "t", "analysis": "a"}}) == "observation: t - a"
    print("ok  record_text: noise skipped, non-JSON and non-object content do not crash")


def test_ask_prints_only_the_answer():
    st = Stubber(q.client)
    st.add_response("create_chat", {"executionId": CHAT, "createdAt": NOW}, {"agentSpaceId": S})

    def fake_send_message(**kw):
        validate_parameters(kw, q.client.meta.service_model.operation_model("SendMessage").input_shape)
        assert kw == {"agentSpaceId": S, "executionId": CHAT, "content": "Any 5xx?"}, kw
        return {"events": iter([
            {"responseCreated": {"responseId": "x"}},
            {"contentBlockStart": {"index": 0, "type": "thinking"}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": "I should check alarms"}}}},
            {"contentBlockStart": {"index": 1, "type": "tool_summary"}},
            {"contentBlockDelta": {"index": 1, "delta": {"textDelta": {"text": "Done"}}}},
            {"contentBlockDelta": {"index": 1, "delta": {"jsonDelta": {"partialJson": "{}"}}}},
            {"contentBlockStart": {"index": 2, "type": "text"}},
            {"contentBlockDelta": {"index": 2, "delta": {"textDelta": {"text": "Yes, "}}}},
            {"contentBlockDelta": {"index": 2, "delta": {"textDelta": {"text": "3 alarms."}}}},
            {"contentBlockStart": {"index": 3, "type": "final_response"}},
            {"contentBlockDelta": {"index": 3, "delta": {"textDelta": {"text": "Yes, 3 alarms."}}}},
            {"contentBlockStart": {"index": 4, "type": "chat_title"}},
            {"contentBlockDelta": {"index": 4, "delta": {"textDelta": {"text": "Alarm check"}}}},
            {"responseCompleted": {"responseId": "x"}},
        ])}

    real = q.client.send_message
    q.client.send_message = fake_send_message  # Stubber can't build an event stream
    try:
        with st:
            text, out = run(q.ask, "Any 5xx?")
    finally:
        q.client.send_message = real
    assert text == "Yes, 3 alarms." and out == "Yes, 3 alarms.\n", repr(out)
    print("ok  ask: prints only the text block (no thinking, Done, duplicate, title)")


if __name__ == "__main__":
    test_investigate_full_flow_with_pagination()
    test_needs_approval_and_linked()
    test_timeout()
    test_record_text_edge_cases()
    test_ask_prints_only_the_answer()
    print("ALL OK")
