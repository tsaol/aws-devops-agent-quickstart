# 参考文档

本仓库的代码和一页纸都按下面这些官方资料写成（2026-11 查阅）。

## AWS DevOps Agent 用户指南

入口：<https://docs.aws.amazon.com/devopsagent/latest/userguide/>

| 主题 | 链接 | 本仓库用到的内容 |
|---|---|---|
| 支持的 Region | [Supported Regions](https://docs.aws.amazon.com/devopsagent/latest/userguide/about-aws-devops-agent-supported-regions.html) | 15 个 Region；一个 Agent Space 能调查账号内所有 Region 的资源 |
| CLI 上手 | [CLI onboarding guide](https://docs.aws.amazon.com/devopsagent/latest/userguide/getting-started-with-aws-devops-agent-cli-onboarding-guide.html) | 创建 IAM 角色、`create-agent-space`、`associate-service` |
| 其他上手方式 | [CDK](https://docs.aws.amazon.com/devopsagent/latest/userguide/getting-started-with-aws-devops-agent-getting-started-with-aws-devops-agent-using-aws-cdk.html) · [CloudFormation](https://docs.aws.amazon.com/devopsagent/latest/userguide/getting-started-with-aws-devops-agent-getting-started-with-aws-devops-agent-using-aws-cloudformation.html) · [Terraform](https://docs.aws.amazon.com/devopsagent/latest/userguide/getting-started-with-aws-devops-agent-getting-started-with-aws-devops-agent-using-terraform.html) | 用 IaC 建 Agent Space |
| IAM 权限 | [DevOps Agent IAM permissions](https://docs.aws.amazon.com/devopsagent/latest/userguide/aws-devops-agent-security-devops-agent-iam-permissions.html) | 每个 `aidevops:*` 动作的含义；Operator / 只读策略示例 |
| 问答（Chat） | [On Demand DevOps Tasks](https://docs.aws.amazon.com/devopsagent/latest/userguide/working-with-devops-agent-on-demand-devops-tasks.html) | 能问什么、示例问题、附件限制 |
| 调查 | [Autonomous incident response](https://docs.aws.amazon.com/devopsagent/latest/userguide/production-operations-autonomous-incident-response.html) | 调查流程、triage、`LINKED` 合并 |
| 查看调查 | [Reviewing investigations](https://docs.aws.amazon.com/devopsagent/latest/userguide/working-with-devops-agent-reviewing-investigations.html) | 调查结果里有什么 |
| 配额 | [Quotas](https://docs.aws.amazon.com/devopsagent/latest/userguide/quotas.html) | 每个 Space 默认并发 3 个调查、10 个问答 |
| Webhook 触发 | [Invoking DevOps Agent through Webhook](https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-integrations-and-knowledge-invoking-devops-agent-through-webhook.html) | 不写 SDK 代码的触发方式 |
| EventBridge | [Integrating with Amazon EventBridge](https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-integrations-and-knowledge-integrating-devops-agent-into-event-driven-applications-using-amazon-eventbridge-index.html) | 调查事件推送到 EventBridge |
| MCP / A2A | [Connecting to DevOps Agent Remote Servers](https://docs.aws.amazon.com/devopsagent/latest/userguide/accessing-devops-agent-connecting-to-devops-agent-remote-servers-index.html) | 让其他 Agent 或 IDE 调用 DevOps Agent |
| 预览版迁移到 GA | [Migrating from public preview to GA](https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-integrations-and-knowledge-migrating-from-public-preview-to-general-availability.html) | 预览期用过的话要看 |

## SDK

- boto3 客户端名：`devops-agent`（服务端点前缀 `aidevops`，API 版本 `2026-01-01`）
- boto3 API 参考：<https://docs.aws.amazon.com/boto3/latest/reference/services/devops-agent.html>
- 本仓库测试用的版本：boto3 1.42.97

## 本仓库用到的 API

| API | 作用 |
|---|---|
| `create_chat` | 新建一个问答会话，返回 `executionId` |
| `send_message` | 在会话里提问，返回**事件流**（`contentBlockDelta.delta.textDelta.text` 是文本片段） |
| `create_backlog_task` | 发起任务，`taskType` 为 `INVESTIGATION`（调查）或 `EVALUATION`（预防评估） |
| `get_backlog_task` | 查任务状态：`PENDING_TRIAGE` `PENDING_START` `IN_PROGRESS` `PENDING_CUSTOMER_APPROVAL` `COMPLETED` `FAILED` `TIMED_OUT` `CANCELED` `LINKED` |
| `list_executions` | 列出任务下的执行（调查、缓解、问答等） |
| `list_journal_records` | 读 Agent 的每一步：推理、动作、查过的数据源 |
| `list_recommendations` | 读调查给出的建议 |
| `get_account_usage` | 查本月调查小时数、问答次数等用量 |
