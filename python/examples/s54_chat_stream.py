"""5.4 Chat with streaming answers, several turns in one conversation.

  python s54_chat_stream.py "us-east-1 有几个 S3 bucket？" "其中哪些没开版本控制？"
  python s54_chat_stream.py --verbose "过去 24 小时有哪些告警？"     # also show thinking and tools
  python s54_chat_stream.py --list                                 # recent chats in the Agent Space

IAM: aidevops:CreateChat, aidevops:SendMessage, aidevops:ListChats
"""
import argparse
import sys

from common import client, pages, space_id


def new_chat():
    """create_chat returns an executionId. Reuse it for follow-up questions:
    the agent keeps the earlier turns as context. A new chat starts empty."""
    return client.create_chat(agentSpaceId=space_id())["executionId"]


def send(execution_id, question, verbose=False):
    """Send one message and stream the answer to stdout. Returns (answer, usage).

    send_message returns an event stream: iterate resp["events"]. Each event has one key:
      responseCreated / responseInProgress / responseCompleted (has token usage) / responseFailed
      contentBlockStart  {index, type}  a new block begins; remember its type
      contentBlockDelta  {index, delta: {textDelta: {text}} or {jsonDelta: {partialJson}}}
      contentBlockStop   {index, type, text}
      heartbeat, summary
    Block types: thinking, thinking_duration, context_usage, tool_summary, text,
    final_response, chat_title. Only "text" is the answer; "final_response" repeats it.
    """
    resp = client.send_message(agentSpaceId=space_id(), executionId=execution_id, content=question)
    kind, answer, fallback, usage = {}, [], [], {}
    for event in resp["events"]:
        if "contentBlockStart" in event:
            b = event["contentBlockStart"]
            kind[b["index"]] = b.get("type")
        elif "contentBlockDelta" in event:
            d = event["contentBlockDelta"]
            text = d.get("delta", {}).get("textDelta", {}).get("text")
            t = kind.get(d.get("index"))
            if not text:
                continue
            if t == "text":
                answer.append(text)
                print(text, end="", flush=True)
            elif t == "final_response":
                fallback.append(text)
            elif verbose and t in ("thinking", "tool_summary"):
                print(f"\033[2m[{t}] {text}\033[0m", file=sys.stderr, flush=True)
        elif "responseCompleted" in event:
            usage = event["responseCompleted"].get("usage", {})
        elif "responseFailed" in event:
            f = event["responseFailed"]
            raise RuntimeError(f"{f.get('errorCode')}: {f.get('errorMessage')}")
    if not answer and fallback:  # no "text" block came: use the repeated answer
        answer = fallback
        print("".join(fallback), end="")
    print()
    return "".join(answer), usage


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("questions", nargs="*", help="one or more questions, asked in the same chat")
    p.add_argument("--verbose", action="store_true", help="print thinking and tool steps to stderr")
    p.add_argument("--list", action="store_true", help="list recent chats")
    a = p.parse_args()

    if a.list:
        for c in list(pages("list_chats", "executions", agentSpaceId=space_id()))[:20]:
            print(f"{c['createdAt']:%Y-%m-%d %H:%M}  {c['executionId']}  {c.get('summary') or ''}")
        sys.exit(0)
    if not a.questions:
        p.error("ask at least one question")

    chat = new_chat()
    print(f"chat {chat}\n")
    for q in a.questions:
        print(f"> {q}")
        _, usage = send(chat, q, a.verbose)
        if usage:
            print(f"  (tokens in {usage.get('inputTokens')}, out {usage.get('outputTokens')})\n")
