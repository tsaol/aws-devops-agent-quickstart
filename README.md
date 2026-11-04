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

## License

MIT-0，见 [LICENSE](LICENSE)。
