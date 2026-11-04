# 5. boto3 示例

本章用 Python（boto3）把 AWS DevOps Agent 的常用功能逐个走一遍。每一节的代码都来自 [`python/examples/`](../python/examples/) 里可以直接运行的脚本，**2026-11-04 在真实的 Agent Space 里跑过**（boto3 1.43.123）。

```bash
cd python/examples
pip install -r ../requirements.txt          # boto3 >= 1.43
export AGENT_SPACE_ID=<your-agent-space-id>
export AWS_REGION=us-east-1                  # Agent Space 所在的 Region
python common.py                             # 先确认能连上
```

| 小节 | 脚本 | 做什么 |
|---|---|---|
| [5.1 客户端与分页](#51-客户端与分页) | `common.py` | 建客户端、超时和重试、翻页、错误处理（其他脚本都用它） |
| [5.2 发起一次调查](#52-发起一次调查) | `s52_start_investigation.py` | 创建调查任务，等它结束 |
| [5.3 读取调查过程](#53-读取调查过程) | `s53_read_investigation.py` | 读 Agent 每一步的发现和结论 |
| [5.4 Chat 流式对话](#54-chat-流式对话) | `s54_chat_stream.py` | 多轮提问，流式打印答案 |
| [5.5 预防建议](#55-预防建议) | `s55_prevention.py` | 发起预防评估，读取和处理建议 |
| [5.6 定时触发自定义 Agent](#56-定时触发自定义-agent) | `s56_custom_agent_schedule.py` | 建自定义 Agent，按 cron 定时运行 |
| [5.7 用量与配额](#57-用量与配额) | `s57_usage_and_quotas.py` | 本月用了多少小时，配额是多少 |

> [!NOTE]
> 本章的代码只依赖 boto3。所有调用都用 `devops-agent` 客户端（服务端点前缀 `aidevops`），IAM 动作都是 `aidevops:<操作名>`。每节末尾列出了这一节需要的权限。

---

## 5.1 客户端与分页

### 建客户端

```python
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
```

| 设置 | 为什么 |
|---|---|
| `"devops-agent"` | 服务名。boto3 1.43 起才有完整 API（包括 5.6 用到的 Asset API）。 |
| `region_name` | **Agent Space 所在的 Region**，不是要调查的资源所在的 Region。一个 Agent Space 能看它关联账号的所有 Region。 |
| `read_timeout=300` | `send_message` 是流式返回，Agent 思考时会有一段时间没有数据，默认 60 秒容易超时。 |
| `retries` `adaptive` | 遇到 `ThrottlingException` 自动退避重试。 |

### 翻页

DevOps Agent 的列表接口都会返回 `nextToken`，**一定要翻页读完**。比如调查的 journal 每页最多 100 条，结论在最后一页。

```python
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
```

| 有 boto3 paginator | 没有，要自己按 `nextToken` 循环 |
|---|---|
| `list_agent_spaces` `list_backlog_tasks` `list_executions` `list_journal_records` `list_goals` `list_triggers` `list_assets` | `list_recommendations` `list_chats` |

列表字段名不统一：`list_agent_spaces` → `agentSpaces`，`list_backlog_tasks` → `tasks`，`list_executions` → `executions`，`list_journal_records` → `records`，`list_recommendations` → `recommendations`，`list_assets` 和 `list_triggers` → `items`。

### 错误处理

```python
def error_code(e):
    """Short 'Code: message' for a ClientError (AccessDenied, Validation, Throttling...)."""
    if isinstance(e, ClientError):
        err = e.response.get("Error", {})
        return f"{err.get('Code')}: {err.get('Message')}"
    return f"{type(e).__name__}: {e}"
```

常见错误：

| 错误码 | 常见原因 |
|---|---|
| `AccessDeniedException` | 调用方没有对应的 `aidevops:*` 权限 |
| `ValidationException` | 参数不对。服务端的报错信息通常会写出正确格式，值得仔细读 |
| `ResourceNotFoundException` | `agentSpaceId` / `taskId` 写错，或者 Region 不对 |
| `ThrottlingException` | 调用太频繁；`adaptive` 重试会自动处理 |

**运行**：`python common.py` 列出当前 Region 的 Agent Space，并检查 `AGENT_SPACE_ID`。

**IAM**：`aidevops:ListAgentSpaces`、`aidevops:GetAgentSpace`

---

## 5.2 发起一次调查

调查（investigation）是一个异步任务：创建后服务端开始分析，你轮询它的状态，结束后再去读过程和结论（5.3）。

```python
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
```

| 参数 | 说明 |
|---|---|
| `taskType` | `"INVESTIGATION"`。其他取值：`"EVALUATION"`（预防评估，见 5.5）、`"RELEASE_READINESS_REVIEW"`、`"RELEASE_TESTING"` |
| `title` | 短标题。网页里显示，triage 也用它判断是不是重复的调查 |
| `description` | **写得越具体越好**：几点开始、看到什么现象、哪个服务、影响多大。Agent 从这段文字开始查 |
| `priority` | `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` / `MINIMAL` |
| `clientToken` | 幂等键。网络重试时带同一个值，服务端不会重复创建 |

### 等它结束

```python
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
```

| 状态 | 含义 | 代码怎么做 |
|---|---|---|
| `PENDING_TRIAGE` `PENDING_START` `IN_PROGRESS` `WAITING` | 还在进行 | 继续轮询 |
| `COMPLETED` | 完成 | 去读结论（5.3） |
| `LINKED` | 和已有调查重复，被合并 | 看 `primaryTaskId`，去读主调查 |
| `SKIPPED` | 被 triage 过滤掉 | 看 `statusReason` |
| `PENDING_CUSTOMER_APPROVAL` | Agent 提出了缓解方案，**等人批准** | 停止轮询，去网页处理 |
| `FAILED` `TIMED_OUT` `CANCELED` | 失败、超时、被取消 | 看 `statusReason` |

实测：一个简单的调查（检查 1 小时内的告警）大约 1 分钟完成。

**运行**：

```bash
python s52_start_investigation.py "API 5xx 升高" "14:05 UTC 起 ALB 5xx 超过 5%，影响结账接口"
python s52_start_investigation.py "..." "..." --no-wait      # 只创建，打印 taskId
```

**IAM**：`aidevops:CreateBacklogTask`、`aidevops:GetBacklogTask`

---

## 5.3 读取调查过程

一个调查任务下有一个或多个**执行**（execution），每个执行有自己的 **journal**，记录 Agent 的每一步。

```
task ──┬── execution (agentSubTask = "oncall")
       │      └── journal records: message, utilization, observation, investigation_gap, investigation_result …
       └── execution (子执行，parentExecutionId 指向上一层)
```

```python
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
```

journal 记录有很多类型，大部分是模型原始消息和网页用的数据。实测一次简单调查的记录构成：

| 记录类型 | 条数 | 给谁看 |
|---|---|---|
| `message` | 6 | 模型的原始对话（含工具调用） |
| `utilization` | 5 | 上下文占用，给网页用 |
| `ui_investigation_summary` | 4 | 网页上的摘要卡片 |
| `observation` | 1 | **发现**（title + analysis） |
| `investigation_gap` | 1 | **没查到 / 查不了的地方**（title + description） |
| `investigation_result` | 1 | **结论**（text），通常是最后一条 |

另外还可能有 `root_cause`、`mitigation`。

### 把记录变成一行可读的文字

`content` **大多数时候是 JSON 字符串**，要先解析，不然中文会显示成 `\u6d4b\u8bd5` 这样的转义：

```python
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
```

```python
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
```

### 时间

botocore 把时间转成**本地时区**的 `datetime`。脚本统一打印 UTC：`r["createdAt"].astimezone(dt.timezone.utc)`。

**运行**：

```bash
python s53_read_investigation.py <taskId>                           # 发现和结论的时间线 + 建议
python s53_read_investigation.py <taskId> --types                   # 各类记录各有多少条
python s53_read_investigation.py <taskId> --only investigation_result   # 服务端过滤，只拿结论
```

`--only` 用的是 `list_journal_records` 的 `recordType` 参数，实测服务端会真的只返回这一类记录。

**IAM**：`aidevops:GetBacklogTask`、`aidevops:ListExecutions`、`aidevops:ListJournalRecords`、`aidevops:ListRecommendations`

---

## 5.4 Chat 流式对话

Chat 是同步的问答，答案流式返回，适合查资源、查告警、出报告。

### 开一个会话

```python
def new_chat():
    """create_chat returns an executionId. Reuse it for follow-up questions:
    the agent keeps the earlier turns as context. A new chat starts empty."""
    return client.create_chat(agentSpaceId=space_id())["executionId"]
```

同一个 `executionId` 可以连续发多条消息，Agent 会记得前面的对话。实测：先问「us-east-1 有几个 S3 bucket」，再问「其中名字以 cdk 开头的有几个」，第二个问题能用上第一轮的结果。

### 发消息，读事件流

```python
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
```

`send_message` 返回的不是一个完整的回答，而是一串**事件**。每个回答由多个**内容块**组成，每块有类型：

| 块类型 | 内容 | 打印吗 |
|---|---|---|
| `thinking` | Agent 的思考过程 | 否（`--verbose` 时打到 stderr） |
| `thinking_duration` | 思考用了多久 | 否 |
| `context_usage` | 上下文占用 | 否 |
| `tool_summary` | 「查询中…」「Done」，以及工具调用的 JSON（`jsonDelta`） | 否（`--verbose` 时打到 stderr） |
| `text` | **答案**，流式返回 | 是 |
| `final_response` | 同一个答案再发一次 | 只在没有 `text` 块时用 |
| `chat_title` | 会话标题 | 否 |

> [!IMPORTANT]
> 如果把所有 `textDelta` 都打印出来，答案会出现两遍，中间还夹着「Done」和会话标题。一定要按块类型过滤。

> [!NOTE]
> Agent 的回答来自模型，**同一个问题每次的答案可能不同**。实测问 S3 bucket 数量（实际 27 个），多数回答 27，也出现过 26 和 28。对数字要求严格的场景，请用对应服务的 API 再核对。

**运行**：

```bash
python s54_chat_stream.py "us-east-1 有几个 S3 bucket？" "其中哪些没开版本控制？"
python s54_chat_stream.py --verbose "过去 24 小时有哪些告警？"
python s54_chat_stream.py --list            # 最近的会话
```

`list_chats` 没有 boto3 paginator，`maxResults` 只能是 1–20，超过会报 `ValidationException`。

**IAM**：`aidevops:CreateChat`、`aidevops:SendMessage`、`aidevops:ListChats`

---

## 5.5 预防建议

调查是「出了事再查」，预防是「从过去的调查里找规律，提出长期改进」。Agent 定期（默认每周）做一次**评估**（evaluation），生成或更新**建议**（recommendation），分为可观测性、基础设施、流程治理、代码四类。

```
goal (ONCALL_REPORT，每周一次) ── evaluation task ── recommendations
```

### 看 goal

```python
def goals():
    """list_goals: each goal has a type, a status, and evaluationSchedule {state, expression}.
    ONCALL_REPORT is the built-in weekly prevention review. CUSTOMER_DEFINED goals include
    the schedule triggers of custom agents (5.6): their goalId equals the triggerId."""
    return list(pages("list_goals", "goals", agentSpaceId=space_id()))
```

```python
def default_goal():
    """The built-in prevention goal is the ONCALL_REPORT one. Do not just take goals()[0]:
    every schedule trigger (5.6) also shows up in list_goals as a CUSTOMER_DEFINED goal."""
    gs = [g for g in goals() if g["goalType"] == "ONCALL_REPORT"] or goals()
    return gs[0]["goalId"]
```

> [!WARNING]
> 不要直接取 `list_goals` 的第一个。实测每建一个定时触发器（5.6），`list_goals` 里就会多一个 `CUSTOMER_DEFINED` 类型的 goal，它的 `goalId` 和 `triggerId` 相同。

### 手动发起一次评估

```python
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
```

> [!IMPORTANT]
> 评估任务的 `description` **必须是 JSON**：`{"goal_id": "goal-..."}`。传普通文字会报 `ValidationException: Evaluation task must have a json description containing valid goal_id`。这一点官方文档里没写，是实测时服务端返回的。

服务端自己按计划发起的评估，`description` 也是这个格式，实测为 `{"goal_id": "goal-...", "goal_type": "ONCALL_REPORT", "goal_status": "ACTIVE"}`。

实测：测试环境里一次评估约 1 分钟完成，生成了 2 条新建议。

### 读建议

```python
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
```

建议的 `content.summary` **也是 JSON 字符串**，实测包含这些字段：

| 字段 | 内容 |
|---|---|
| `title` | 标题 |
| `category` | 分类，例如 `MONITORING_AND_OBSERVABILITY`、`PROCESS_AND_GOVERNANCE` |
| `overview` | 概述：发生了什么、影响多大 |
| `background` | 背景：根据哪些调查得出的 |
| `next_steps` | 下一步怎么做 |
| `considerations` | 注意事项、可能的副作用 |
| `affected_incidents` | 相关调查的 ID 列表 |

```python
def parse_summary(rec):
    """Return content.summary as a dict. Falls back to {"overview": text} if it is plain text."""
    text = rec["content"].get("summary") or ""
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"overview": text}
    except ValueError:
        return {"overview": text}
```

### 处理建议

```python
def set_status(rec_id, status, why=None):
    """update_recommendation. additionalContext is your reason in plain words;
    the agent uses discard reasons to shape later recommendations."""
    params = dict(agentSpaceId=space_id(), recommendationId=rec_id, status=status,
                  clientToken=str(uuid.uuid4()))
    if why:
        params["additionalContext"] = why
    return client.update_recommendation(**params)["recommendation"]
```

| 网页按钮 | API 状态 | 说明 |
|---|---|---|
| Keep | `ACCEPTED` | 留在待办里跟踪 |
| Discard | `REJECTED` | 丢弃，可以在 `additionalContext` 写理由，Agent 会参考 |
| Implemented | `COMPLETED` | 已经做了 |

网页按钮和 API 状态的对应关系官方文档没有写明，上表是按名称推断的。实测 `ACCEPTED` 之后可以再改回 `PROPOSED`。没有被保留或实施的建议，大约 6 周后可能被自动移除。

### 开关定时评估

```python
def set_schedule(enabled, goal_id=None):
    """update_goal can switch the evaluation schedule on or off. It cannot change the
    expression (rate(7 days) by default)."""
    goal_id = goal_id or default_goal()
    g = client.update_goal(agentSpaceId=space_id(), goalId=goal_id,
                           evaluationSchedule={"state": "ENABLED" if enabled else "DISABLED"},
                           clientToken=str(uuid.uuid4()))["goal"]
    return g
```

实测：把定时评估关掉再打开后，大约 7 分钟内服务端就自动发起了一次定时评估。如果不想马上跑一次，就别随手开关。

**运行**：

```bash
python s55_prevention.py goals
python s55_prevention.py evaluate                     # 等它完成，约 1 分钟起
python s55_prevention.py list --task <evaluationTaskId>
python s55_prevention.py show <recommendationId>
python s55_prevention.py keep <recommendationId>
python s55_prevention.py discard <recommendationId> --why "我们用 Datadog 告警，不用 CloudWatch"
python s55_prevention.py schedule off                 # 暂停每周评估
```

**IAM**：`aidevops:ListGoals`、`aidevops:UpdateGoal`、`aidevops:CreateBacklogTask`、`aidevops:GetBacklogTask`、`aidevops:ListRecommendations`、`aidevops:GetRecommendation`、`aidevops:UpdateRecommendation`

---

## 5.6 定时触发自定义 Agent

自定义 Agent（custom agent）是你自己定义的 Agent：一段系统提示词，加上可选的 skills、工具和记忆。它是一种 **asset**（和 skill 一样用 Asset API 管理），可以用**触发器**（trigger）按时间自动运行。

```
custom_agent asset (AGENT.md = 系统提示词) ◀── trigger (TIME_BASED, cron/rate)
```

### 建自定义 Agent

```python
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
```

| 字段 | 说明 |
|---|---|
| `metadata.name` | 必填，小写字母、数字、连字符，1–64 个字符 |
| `metadata.skills` | 可选。**skill 的 assetId**，不是名字；skill 要先装进 Agent Space（用仓库的 `install_skills.py`） |
| `metadata.tools` / `memory_stores` | 可选。MCP 工具一般建好后在 Chat 里让 Agent 添加 |
| `content` | 系统提示词，放在名为 `AGENT.md` 的文本文件里 |

### 按时间运行

```python
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
```

| 字段 | 说明 |
|---|---|
| `type` | 目前只支持 `"TIME_BASED"` |
| `condition.schedule.expression` | EventBridge 语法，**UTC**：`rate(1 hour)`、`rate(7 days)`、`cron(0 1 ? * MON *)`（日和星期必须有一个是 `?`） |
| `action` | JSON 文档：`{"actionType": "create:task", "task": {"agent": "custom:<assetId>", "description": "<提示词>"}}` |
| `status` | `"Active"` 或 `"Inactive"`（暂停） |

> [!IMPORTANT]
> `action` 在 SDK 里是自由格式，客户端不检查，只有服务端检查。实测：
> - 每次运行的提示词放在 **`task.description`**。写成 `userPrompt`、`prompt` 等其他字段名，服务端**不报错，但会悄悄丢掉**。建完用 `get_trigger` 读回来确认一下。
> - `condition.schedule.spec` 只接受 `cron` 和 `timeRange`，不能放提示词。
> - `type`、`condition`、`action` 建好后不能改，只能删掉重建；`status` 可以用 `update_trigger` 改。

```python
def show_trigger(t):
    task = t["action"].get("task", {})
    prompt = f'  prompt "{task["description"]}"' if task.get("description") else ""
    return f"{t['triggerId']}  {t['status']:8}  {t['condition']['schedule']['expression']:22} {task.get('agent')}{prompt}"
```

### 实测结果

| 步骤 | 结果 |
|---|---|
| `create_asset(assetType="custom_agent")` | 成功，读回 `metadata` 里有 `name`、`status: ACTIVE`、`skills`、`tools` |
| `create_trigger`（一次性 cron 和 `rate(5 minutes)` 两种） | 成功，`get_trigger` 读回的 `action` 里有 `task.description` 提示词 |
| `update_trigger` 暂停 / 恢复 | 成功，`status` 在 `Inactive` 和 `Active` 之间切换 |
| `delete_trigger` / `delete_asset` | 成功 |
| 触发器到点后有没有真的运行 | **未能确认**。`rate(5 minutes)` 的触发器保持 Active 12 分钟，期间 `list_backlog_tasks`、`list_chats` 和 `list_goals`（`lastTaskId`）都没有出现这个自定义 Agent 的运行记录。可能是自定义 Agent 的运行记录不通过这些 API 返回（网页上 Agent 页面的 **History** 标签可以看），也可能是调度还没开始。上线前请在网页的 History 里确认一次 |

> [!NOTE]
> 触发器 ID 以 `goal-` 开头，`list_goals` 里会出现一个同 ID 的 `CUSTOMER_DEFINED` goal，它的 `evaluationSchedule.expression` 就是触发器的表达式。

**运行**：

```bash
python s56_custom_agent_schedule.py create weekly-health --prompt-file prompt.md --skill aws-health-events
python s56_custom_agent_schedule.py schedule <agentAssetId> "cron(0 1 ? * MON *)" --prompt "本周重点看告警"
python s56_custom_agent_schedule.py triggers
python s56_custom_agent_schedule.py pause <triggerId>        # Inactive
python s56_custom_agent_schedule.py delete-trigger <triggerId>
python s56_custom_agent_schedule.py delete-agent <agentAssetId>
```

想马上运行一次：官方文档里没有「立即运行自定义 Agent」的 API。可以在网页上点 **Run Now**，在 Chat 里说「Run my weekly-health agent」，或者像本节测试一样，建一个几分钟后触发的 cron。

**IAM**：`aidevops:CreateAsset`、`aidevops:ListAssets`、`aidevops:DeleteAsset`、`aidevops:CreateTrigger`、`aidevops:ListTriggers`、`aidevops:GetTrigger`、`aidevops:UpdateTrigger`、`aidevops:DeleteTrigger`

---

## 5.7 用量与配额

### 本月用量

```python
def usage():
    """get_account_usage(): no parameters, account level (all Agent Spaces in the Region).
    Each field is {"usage": hours used, "limit": monthly limit, -1 = no limit}.
    usagePeriodStartTime / usagePeriodEndTime: the current month so far."""
    return client.get_account_usage()
```

| 字段 | 计的是什么（单位都是**小时**） |
|---|---|
| `monthlyAccountInvestigationHours` | 调查 |
| `monthlyAccountEvaluationHours` | 预防评估 |
| `monthlyAccountOnDemandHours` | Chat 问答 |
| `monthlyAccountSystemLearningHours` | 系统学习（Agent 学习你的环境） |
| `monthlyAccountGraderHours` | 调查评审 |

每个字段是 `{"usage": 已用小时, "limit": 上限}`，`limit` 为 `-1` 表示不限。统计范围是**整个账号**在这个 Region 的所有 Agent Space，从本月 1 日开始。

实测输出：

```
usage 2026-11-01 .. 2026-11-04 14:50 (hours, whole account)
  调查 investigation                 0.10 h  no limit
  预防评估 evaluation                  0.00 h  no limit
  问答 on-demand chat                0.06 h  no limit
  系统学习 system learning             0.51 h  no limit
  调查评审 grader                      0.00 h  no limit
```

### 配额

配额不在 `devops-agent` API 里，在 **Service Quotas**：

```python
def quotas(region=REGION):
    """Quotas live in Service Quotas, not in the devops-agent API.

    1. list_services -> find the DevOps Agent service code by name
    2. list_service_quotas -> values applied to this account (after any increase)
    3. list_aws_default_service_quotas -> defaults, for quotas never changed
    Adjustable quotas can be raised with request_service_quota_increase.
    """
    sq = boto3.client("service-quotas", region_name=region)
    services = [s for page in sq.get_paginator("list_services").paginate() for s in page["Services"]
                if "devops agent" in s["ServiceName"].lower()]
    out = []
    for s in services:
        code = s["ServiceCode"]
        applied = {q["QuotaCode"]: q for page in sq.get_paginator("list_service_quotas").paginate(ServiceCode=code)
                   for q in page["Quotas"]}
        for page in sq.get_paginator("list_aws_default_service_quotas").paginate(ServiceCode=code):
            for q in page["Quotas"]:
                q = applied.get(q["QuotaCode"], q)
                out.append((code, q["QuotaCode"], q["QuotaName"], q["Value"], q["Adjustable"]))
    return out
```

官方文档列出的主要默认配额（[Quotas](https://docs.aws.amazon.com/devopsagent/latest/userguide/quotas.html)）：

| 配额 | 默认值 | 可调 |
|---|---|---|
| 每个账号每个 Region 的 Agent Space | 100 | 是 |
| 每个 Agent Space 同时进行的调查 | 3 | 是 |
| 每个 Agent Space 同时进行的评估 | 1 | 否 |
| 每个 Agent Space 同时进行的 Chat | 10 | 是 |
| 每个 Agent Space 的自定义 Agent | 200 | 否 |
| 每个自定义 Agent 同时运行 | 1 | 否 |
| 自定义 Agent 单次运行超时 | 1 小时 | 否 |

> [!NOTE]
> 本章测试时，测试环境的角色没有 Service Quotas 权限，所以配额部分只验证了「权限不足时给出明确提示」，**没有实际读到配额值**。需要的权限：`servicequotas:ListServices`、`servicequotas:ListServiceQuotas`、`servicequotas:ListAWSDefaultServiceQuotas`。

**运行**：

```bash
python s57_usage_and_quotas.py            # 用量 + 配额
python s57_usage_and_quotas.py --usage    # 只看用量
```

**IAM**：`aidevops:GetAccountUsage`；配额部分另需上面三个 `servicequotas:*` 权限

---

## 本章测试情况

| 小节 | 实测（2026-11-04，us-east-1 测试 Agent Space） |
|---|---|
| 5.1 | 列出 Agent Space、校验 `AGENT_SPACE_ID` |
| 5.2 | 调查约 1 分钟完成，状态流转 `PENDING_START` → `IN_PROGRESS` → `COMPLETED` |
| 5.3 | 时间线、记录类型统计、`--only` 服务端过滤都正常 |
| 5.4 | 两轮对话，第二轮用上了第一轮的上下文；`--list` 正常 |
| 5.5 | 评估约 1 分钟完成并生成 2 条建议；`ACCEPTED` 后可改回 `PROPOSED`；定时评估关掉再打开 |
| 5.6 | 建 Agent、建触发器（提示词存进 `task.description`）、暂停 / 恢复、删除都通过；**触发器到点后是否运行，通过 API 未能观察到**（见 5.6 实测结果） |
| 5.7 | 用量正常；配额因权限不足未读到值 |

测试中创建的自定义 Agent、触发器都已删除；建议状态和定时评估都已恢复原样。
