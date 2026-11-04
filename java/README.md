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

> **注意**：`SendMessage` 是事件流，**只能用 `DevOpsAgentAsyncClient`** 配合 `SendMessageResponseHandler`，同步客户端没有这个方法。其他操作用同步的 `DevOpsAgentClient`。

```bash
mvn test            # ONLINE=1 mvn test 另外检查 GitHub URL
```

更多说明见[根目录 README](../README.md)。
