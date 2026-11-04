"""Run the quick start flow against botocore Stubber.

Stubber checks every request against the real devops-agent API model,
so wrong names, missing required params, or bad enum values fail here.
"""
import datetime as dt
import io
import os
import sys
from contextlib import redirect_stdout

os.environ["AGENT_SPACE_ID"] = "00000000-0000-0000-0000-000000000000"
os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botocore.stub import Stubber  # noqa: E402

import devops_agent_quickstart as q  # noqa: E402

S = os.environ["AGENT_SPACE_ID"]
now = dt.datetime(2026, 11, 4, 14, 5, tzinfo=dt.timezone.utc)


def task(status, ex=None):
    t = {"agentSpaceId": S, "taskId": "t-1", "title": "5xx spike", "taskType": "INVESTIGATION",
         "priority": "HIGH", "status": status, "createdAt": now, "updatedAt": now, "version": 1}
    if ex:
        t["executionId"] = ex
    return {"task": t}


st = Stubber(q.client)
st.add_response("create_backlog_task", task("PENDING_START"), {
    "agentSpaceId": S, "taskType": "INVESTIGATION", "title": "5xx spike",
    "description": "ALB 5xx > 5%", "priority": "HIGH"})
st.add_response("get_backlog_task", task("IN_PROGRESS", "e-1"), {"agentSpaceId": S, "taskId": "t-1"})
st.add_response("get_backlog_task", task("COMPLETED", "e-1"), {"agentSpaceId": S, "taskId": "t-1"})
st.add_response("list_executions", {"executions": [{
    "agentSpaceId": S, "executionId": "e-1", "agentSubTask": "INVESTIGATION",
    "createdAt": now, "updatedAt": now, "executionStatus": "STOPPED"}]},
    {"agentSpaceId": S, "taskId": "t-1"})
st.add_response("list_journal_records", {"records": [{
    "agentSpaceId": S, "executionId": "e-1", "recordId": "r-1", "createdAt": now,
    "recordType": "finding", "content": {"text": "ALB target group sg-123 lost port 443"}}]},
    {"agentSpaceId": S, "executionId": "e-1", "order": "ASC"})
st.add_response("list_recommendations", {"recommendations": [{
    "agentSpaceArn": "arn:aws:aidevops:us-east-1:111122223333:agentspace/" + S,
    "recommendationId": "rec-1", "taskId": "t-1", "title": "Restore SG rule",
    "content": {"summary": "Re-add inbound 443 to the ALB target SG"}, "status": "PROPOSED",
    "priority": "HIGH", "createdAt": now, "updatedAt": now, "version": 1}]},
    {"agentSpaceId": S, "taskId": "t-1"})
st.add_response("create_chat", {"executionId": "c-1", "createdAt": now}, {"agentSpaceId": S})

with st:
    out = io.StringIO()
    with redirect_stdout(out):
        t = q.investigate("5xx spike", "ALB 5xx > 5%", poll_seconds=0)
    assert t["status"] == "COMPLETED", t
    text = out.getvalue()
    assert "lost port 443" in text and "Restore SG rule" in text, text
    print(text)

    # send_message returns an event stream; Stubber can't build one, so fake only that call.
    def fake_send_message(**kw):
        q.client.meta.service_model.operation_model("SendMessage")  # exists
        assert kw == {"agentSpaceId": S, "executionId": "c-1", "content": "Any 5xx in the last hour?"}
        return {"events": iter([
            {"responseCreated": {"responseId": "x"}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": "Yes, "}}}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": "3 alarms."}}}},
            {"responseCompleted": {"responseId": "x"}},
        ])}

    real = q.client.send_message
    q.client.send_message = fake_send_message
    out = io.StringIO()
    with redirect_stdout(out):
        q.ask("Any 5xx in the last hour?")
    q.client.send_message = real
    assert out.getvalue().strip() == "Yes, 3 alarms.", out.getvalue()
    st.assert_no_pending_responses()

# SendMessage params still need checking against the model
from botocore.validate import validate_parameters  # noqa: E402

validate_parameters({"agentSpaceId": S, "executionId": "c-1", "content": "hi"},
                    q.client.meta.service_model.operation_model("SendMessage").input_shape)
print("ALL OK")
