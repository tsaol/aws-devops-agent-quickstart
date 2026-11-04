# AWS DevOps Agent Python Quick Start

用 Python（boto3）调用 [AWS DevOps Agent](https://docs.aws.amazon.com/devopsagent/latest/userguide/)：向 Agent 提问，发起故障调查，读取调查过程和建议。

*Call AWS DevOps Agent from Python: ask questions, start investigations, read the agent's steps and recommendations.*

| 文件 | 内容 |
|---|---|
| [`docs/onepager.html`](docs/onepager.html) · [`docs/onepager.pdf`](docs/onepager.pdf) | 一页纸指南（A4，可打印） |
| [`devops_agent_quickstart.py`](devops_agent_quickstart.py) | 可运行的示例脚本 |
| [`iam-policy.json`](iam-policy.json) | 脚本需要的最小 IAM 权限 |
| [`docs/references.md`](docs/references.md) | 官方参考文档和 API 说明 |
| [`install_skills.py`](install_skills.py) | 把官方 skills 批量装进 Agent Space |
| [`tests/`](tests/) | 离线测试（不需要 AWS 账号） |
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

结束状态：`COMPLETED`、`FAILED`、`TIMED_OUT`、`CANCELED`，还有 `LINKED`（被合并到已有的同类调查）和 `SKIPPED`（被 triage 跳过）。`WAITING` 表示还在等待，脚本会继续轮询。

## 测试

测试用 botocore `Stubber`，会按官方 API 模型检查每个请求的接口名、必填参数和枚举值，不会调用 AWS：

```bash
python tests/test_quickstart.py                    # 问答和调查脚本
python tests/test_install_skills.py                # 47 个 skill 的 frontmatter、zip 打包、安装流程
python tests/test_install_skills.py --online       # 另外检查 47 个 GitHub 导入 URL 都能打开
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

## 怎么使用这些 Skills

### 1. Skill 是什么、什么时候生效

一个 skill 是一个目录，核心是 `SKILL.md`：开头的 frontmatter 写 `name` 和 `description`，正文写排查步骤。装进 Agent Space 后**不用手动调用**：Agent 在问答或调查时，会根据 `description` 判断当前问题是否相关，相关就自动加载并按步骤执行。

每个 skill 还指定了**在哪类 agent 里生效**，写在 frontmatter 的 `aws-devops-agent-skills.agent-types` 里：

| agent 类型 | 什么时候用 | 例子 |
|---|---|---|
| `CHAT` | 你在聊天窗口提问时 | 大部分 review 类 skill |
| `INCIDENT_TRIAGE` | 新告警进来、决定要不要调查时 | `skip-scheduled-maintenance`（维护窗口内跳过低优先级告警） |
| `INCIDENT_RCA` | 调查根因时 | `aws-health-events`、`aws-routing`、`support-cases` |
| `RELEASE_TESTING` | 发布测试时 | `honeycomb-verify-recent-trace` |

运行 `python install_skills.py list` 可以看到全部 47 个 skill 各自的类型。

### 2. 装之前：准备权限

部分 skill 要额外的 IAM 权限，每个 skill 的 `README.md` 里 **Prerequisites** 一节写了。大部分已经包含在 Agent Space 角色的托管策略 `AIDevOpsAgentAccessPolicy` 里。缺的可以用官方模板一次性补齐：

```bash
aws cloudformation deploy \
  --template-file tools-for-devops-agent/cloudformation/devops-agent-skill-policies/devops-agent-skill-policies.yaml \
  --stack-name devops-agent-skill-policies \
  --parameter-overrides ExistingRoleName=<Agent Space 用的 IAM 角色名> \
  --capabilities CAPABILITY_NAMED_IAM
```

### 3. 安装：三种方式选一种

**方式 A：控制台（装一两个时最简单）**

Agent Space 网页 → **Knowledge** → **Skills** → **Add skill** → **Import from repository**，填 skill 目录的 URL，例如：

```
https://github.com/aws/tools-for-devops-agent/tree/main/skills/aws-routing
```

然后选 agent 类型（按上表填）和状态 Active。需要先在 Agent Space 关联一个 GitHub 账号（任何账号都能导入公开仓库）。以后官方更新了，打开这个 skill 点 **Sync** 就行。

**方式 B：上传 zip（不想连 GitHub 时）**

```bash
python install_skills.py zip aws-routing      # 生成 dist/aws-routing.zip
```

然后在 **Add skill** → **Upload skill** 里上传。脚本只打包 Agent 运行时会读的 `SKILL.md`、`references/`、`assets/`，去掉 `evals/`、`README.md` 这些开发文件，`SKILL.md` 放在 zip 根目录。限制：最大 6 MB，不能有 `scripts/` 目录（47 个 skill 都满足，最大的约 250 KB）。

**方式 C：用代码批量装（推荐，新 Agent Space 一次装好）**

```bash
pip install -r requirements.txt               # boto3 >= 1.43 才有 Asset API
export AGENT_SPACE_ID=<your-agent-space-id>
export AWS_REGION=us-east-1

python install_skills.py install aws-health-events support-cases aws-routing   # 装指定的
python install_skills.py install --all                                         # 47 个全装
python install_skills.py install aws-routing --from-github                     # 让 Agent Space 直接从 GitHub 拉
python install_skills.py installed                                             # 看已经装了哪些
```

脚本调用 `create_asset`（`assetType="skill"`），agent 类型自动从 `SKILL.md` 读取，**已经装过的同名 skill 会跳过**，所以可以重复运行。需要的 IAM 权限：`aidevops:CreateAsset`、`aidevops:ListAssets`。每个 Agent Space 最多 200 个自建 skill。

### 4. 验证是否生效

很多 skill 的 `README.md` 里有示例问题（比如 `aws-health-events` 的 "sample prompts"）。在 Agent Space 聊天里问一个，或者用本仓库的脚本：

```bash
python devops_agent_quickstart.py ask "过去 7 天有没有影响我账号的 AWS Health 事件？"
```

Agent 应该自动加载对应的 skill（这里是 `aws-health-events`），回答里会用到 AWS Health 事件。如果回答和没装时一样，检查 skill 的状态是否 Active、agent 类型是否包含 `CHAT`。

### 5. 推荐先装的

| 目的 | 先装这几个 |
|---|---|
| 所有故障调查 | `aws-health-events`、`support-cases`（官方建议每次调查都先用）、`investigation-cost-guardrail`（防止调查时跑贵的查询） |
| 网络问题 | `aws-routing`、`aws-vpc-dns-investigation`、`aws-natgw-traffic-analysis` |
| 减少误报 | `skip-scheduled-maintenance`（先改成你自己的维护窗口再上传） |
| 定期体检 | `service-quota-check`、`aws-backup-coverage-review`、各服务的 `*-operation-review` |

### 6. 改成自己的 skill

官方 skill 可以当模板：复制一个目录，改 `name`、`description` 和步骤，再用上面任一方式安装。写好 `description` 最关键：写清楚**什么症状、什么服务、什么错误**时用它，太笼统的话 Agent 会直接跳过。详见[官方 Skills 文档](https://docs.aws.amazon.com/devopsagent/latest/userguide/about-aws-devops-agent-devops-agent-skills.html)。

> 这些是官方的 sample code。上生产前请先在非生产环境测试，并检查 IAM 权限。最新版本以官方仓库为准。

## License

本仓库自己的代码和文档：MIT-0，见 [LICENSE](LICENSE)。

`tools-for-devops-agent/` 目录：Apache-2.0，见 [tools-for-devops-agent/LICENSE](tools-for-devops-agent/LICENSE) 和 [NOTICE](tools-for-devops-agent/NOTICE)。
