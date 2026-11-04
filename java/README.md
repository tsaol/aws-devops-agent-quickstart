# ☕ Java

Java 17+，Maven，[`software.amazon.awssdk:devopsagent`](https://central.sonatype.com/artifact/software.amazon.awssdk/devopsagent) 2.57+（2.57 之前没有 `sourceUrl`）。

```bash
mvn -q package      # 生成 target/quickstart.jar（包含依赖）
export AGENT_SPACE_ID=<your-agent-space-id> AWS_REGION=us-east-1

java -jar target/quickstart.jar ask "过去 24 小时有哪些告警？"
java -jar target/quickstart.jar investigate "API 5xx 升高" "14:05 UTC 起 5xx 超过 5%"

java -jar target/quickstart.jar skills list | zip [skill...] | installed
java -jar target/quickstart.jar skills install <skill...> [--from-github]
java -jar target/quickstart.jar skills install --all [--include-examples] [--include-third-party]
```

| 文件 | 内容 |
|---|---|
| `Main.java` | 命令行入口 |
| `QuickStart.java` | `ask`、`investigate`、`ChatAnswer`（事件流处理） |
| `Skills.java` | 安装 skills（`createAsset`，zip 用 `java.util.zip`） |
| `src/test/` | JUnit 5 + Mockito 离线测试 |

- `skills` 命令会自动找到仓库里的 `tools-for-devops-agent/skills/`：先从当前目录往上找，再从 jar 所在位置往上找。jar 拷到仓库外面用时，设置 `SKILLS_DIR=/path/to/tools-for-devops-agent/skills`。
- `skills zip` 输出到 `java/dist/`。
- 出错时只打印一行原因：成功 0、出错 1、用法错误 2，和 Python、Node.js 版一样。

> **注意**：`SendMessage` 是事件流，**只能用 `DevOpsAgentAsyncClient`** 配合 `SendMessageResponseHandler`，同步客户端没有这个方法。其他操作用同步的 `DevOpsAgentClient`。

```bash
mvn test            # ONLINE=1 mvn test 另外检查 GitHub URL
```

更多说明见[根目录 README](../README.md)。
