# 🐍 Python

Python 3.10+，boto3 ≥ 1.43（Asset API 从 1.43 开始有）。

```bash
pip install -r requirements.txt
export AGENT_SPACE_ID=<your-agent-space-id> AWS_REGION=us-east-1

python devops_agent_quickstart.py ask "过去 24 小时有哪些告警？"
python devops_agent_quickstart.py investigate "API 5xx 升高" "14:05 UTC 起 5xx 超过 5%"

python install_skills.py list | zip [skill...] | installed
python install_skills.py install <skill...> [--from-github]
python install_skills.py install --all [--include-examples] [--include-third-party]
```

| 文件 | 内容 |
|---|---|
| `devops_agent_quickstart.py` | `ask`（`create_chat` + `send_message` 事件流）、`investigate`（`create_backlog_task` → 轮询 → journal → 建议） |
| `install_skills.py` | 把 [`../skills/`](../skills/) 里的官方 skills 装进 Agent Space（`create_asset`，zip 或 `sourceUrl`） |
| `examples/` | [boto3 示例](../docs/boto3-examples.md)：5.1 客户端与分页 → 5.7 用量与配额，每个小节一个脚本 |
| `tests/` | botocore `Stubber` 离线测试，按官方 API 模型校验请求；`--online` 另外检查 GitHub URL |

```bash
python tests/test_quickstart.py
python tests/test_install_skills.py [--online]
python tests/test_examples.py
```

更多说明见[根目录 README](../README.md)。
