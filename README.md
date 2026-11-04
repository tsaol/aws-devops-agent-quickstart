# AWS DevOps Agent Python Quick Start

用 Python（boto3）调用 [AWS DevOps Agent](https://docs.aws.amazon.com/devopsagent/latest/userguide/)：向 Agent 提问，发起故障调查，读取调查过程和建议。

*Call AWS DevOps Agent from Python: ask questions, start investigations, read the agent's steps and recommendations.*

| 文件 | 内容 |
|---|---|
| [`docs/onepager.html`](docs/onepager.html) · [`docs/onepager.pdf`](docs/onepager.pdf) | 一页纸指南（A4，可打印） |
| [`devops_agent_quickstart.py`](devops_agent_quickstart.py) | 可运行的示例脚本 |
| [`iam-policy.json`](iam-policy.json) | 脚本需要的最小 IAM 权限 |
| [`docs/references.md`](docs/references.md) | 官方参考文档和 API 说明 |
| [`tests/test_quickstart.py`](tests/test_quickstart.py) | 离线测试（不需要 AWS 账号） |
| [`tools-for-devops-agent/`](tools-for-devops-agent/) | 官方 [aws/tools-for-devops-agent](https://github.com/aws/tools-for-devops-agent) 的完整副本：47 个 Skills、9 个 Custom Agents、6 个 MCP servers、CloudFormation 模板（Apache-2.0） |

## 准备

1. **一个 Agent Space**，已经关联要监控的 AWS 账号。可以用控制台、[CLI](https://docs.aws.amazon.com/devopsagent/latest/userguide/getting-started-with-aws-devops-agent-cli-onboarding-guide.html)、CDK、CloudFormation 或 Terraform 创建。记下 `agentSpaceId`。
2. **Region**：Agent Space 所在的 Region，要在[支持列表](https://docs.aws.amazon.com/devopsagent/latest/userguide/about-aws-devops-agent-supported-regions.html)里。一个 Agent Space 能调查账号内所有 Region 的资源。
3. **Python 3.10+** 和新版 boto3：

   ```bash
   pip install -r requirements.txt
   ```

4. **IAM 权限**：把 [`iam-policy.json`](iam-policy.json) 附加给运行脚本的用户或角色。

## 运行

```bash
export AGENT_SPACE_ID=<your-agent-space-id>
export AWS_REGION=us-east-1          # Agent Space 所在的 Region

# 问答：流式打印回答
python devops_agent_quickstart.py ask "过去 24 小时有哪些告警触发了？"

# 调查：发起 → 每 30 秒查一次状态 → 打印 Agent 每一步和建议
python devops_agent_quickstart.py investigate "结账 API 5xx 升高" "14:05 UTC 起 ALB 5xx 超过 5%"
```

## 调查的调用顺序

```
create_backlog_task  →  get_backlog_task（轮询）  →  list_executions
                     →  list_journal_records（每一步）  →  list_recommendations（建议）
```

结束状态：`COMPLETED`、`FAILED`、`TIMED_OUT`、`CANCELED`，还有 `LINKED`（被合并到已有的同类调查）。

## 测试

测试用 botocore `Stubber`，会按官方 API 模型检查每个请求的接口名、必填参数和枚举值，不会调用 AWS：

```bash
python tests/test_quickstart.py
```

## 注意

- `send_message` 返回的是事件流，要用循环读。
- 每个 Agent Space 默认最多并发 3 个调查、10 个问答（[配额](https://docs.aws.amazon.com/devopsagent/latest/userguide/quotas.html)）。
- Lambda 自带的 boto3 可能太旧，没有 `devops-agent` 客户端，要把新版 boto3 一起打包。

## 官方 Skills 和工具

[`tools-for-devops-agent/`](tools-for-devops-agent/) 是官方仓库的完整副本，没有改动，来源 commit 见 [UPSTREAM.md](tools-for-devops-agent/UPSTREAM.md)。

| 场景 | Skills（[`tools-for-devops-agent/skills/`](tools-for-devops-agent/skills/)） |
|---|---|
| 每次调查先用 | `aws-health-events`、`support-cases` |
| 网络 | `aws-routing`、`aws-vpc-dns-investigation`、`aws-natgw-traffic-analysis` |
| 容器 | `aws-eks-operations-review`、`eks-upgrade-readiness`、`aws-eks-healthdashboard`、`ecs-operation-review` |
| 数据库和数据 | `database-rds-devops`、`rds-operation-review`、`database-migration-service-expertise`、`redshift-support-specialist`、`msk-operations`、`analytics-opensearch-expertise`、`firehose-operation-review` |
| 存储和备份 | `storage-s3-resiliency-expertise`、`aws-backup-coverage-review`、`aws-fsxn-operations-review`、`storage-fsx-windows-sla-optimizer` |
| AI/ML | `bedrock-operation-review`、`bedrock-adoption-readiness`、`sagemaker-ai-ops-review`、`aiml-gpu-training-cluster-investigation`、`aiml-access-diagnostics`、`agentcore-ops-review`、`agentcore-observability-setup` |
| 成本 | `investigation-cost-guardrail`、`devops-agent-cost-insights`、`cloudtrail-cost-optimization`、`config-cost-optimization`、`guardduty-cost-optimization` |
| 容量和变更 | `service-quota-check`、`skip-scheduled-maintenance`、`live-streaming-event-readiness-review` |
| 第三方和安全 | Honeycomb（7 个）、`grafana-cloud-investigation`、`sumo-logic-investigator`、`wiz-security-context`、`enrich-with-aws-security-agent`、`crm-production-investigation-guidelines` |

其他内容：

- **Custom Agents**（[`custom-agents/`](tools-for-devops-agent/custom-agents/)）：健康报告、运维评审、EKS 评审、配额监控、工单报告、成本看板等，可以定时运行。
- **MCP servers**（[`mcp/`](tools-for-devops-agent/mcp/)）：EKS 节点诊断、VPC DNS 诊断、RDS、Redshift、ECS 日志、EMR Spark。
- **CloudFormation**（[`cloudformation/`](tools-for-devops-agent/cloudformation/)）：
  - `devops-agent-alarm-investigations`：CloudWatch 告警自动变成调查，不用自己写 Lambda。
  - `devops-agent-skill-policies`：给 skills 补齐需要的 IAM 权限。

**装到 Agent Space**：在 Agent Space 的 Skills 页选「从 GitHub 导入」，填 skill 目录的 URL，比如 `https://github.com/aws/tools-for-devops-agent/tree/main/skills/aws-routing`。也可以把目录打成 zip 上传（最大 6 MB，必须有 `SKILL.md`）。详见[官方文档](https://docs.aws.amazon.com/devopsagent/latest/userguide/about-aws-devops-agent-devops-agent-skills.html)。

> 这些是官方的 sample code。上生产前请先在非生产环境测试，并检查 IAM 权限。最新版本以官方仓库为准。

## License

本仓库自己的代码和文档：MIT-0，见 [LICENSE](LICENSE)。

`tools-for-devops-agent/` 目录：Apache-2.0，见 [tools-for-devops-agent/LICENSE](tools-for-devops-agent/LICENSE) 和 [NOTICE](tools-for-devops-agent/NOTICE)。
