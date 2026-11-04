# 🟩 Node.js

Node.js 20+，[`@aws-sdk/client-devops-agent`](https://www.npmjs.com/package/@aws-sdk/client-devops-agent)（AWS SDK v3）。

```bash
npm install
export AGENT_SPACE_ID=<your-agent-space-id> AWS_REGION=us-east-1

node src/quickstart.mjs ask "过去 24 小时有哪些告警？"
node src/quickstart.mjs investigate "API 5xx 升高" "14:05 UTC 起 5xx 超过 5%"

node src/install-skills.mjs list | zip [skill...] | installed
node src/install-skills.mjs install <skill...> [--from-github]
node src/install-skills.mjs install --all [--include-examples] [--include-third-party]
```

| 文件 | 内容 |
|---|---|
| `src/quickstart.mjs` | `ask`（`SendMessageCommand` 返回 async iterable）、`investigate` |
| `src/install-skills.mjs` | 安装 skills（`CreateAssetCommand`，zip 用 [fflate](https://www.npmjs.com/package/fflate) 打包） |
| `test/` | `node:test` + `aws-sdk-client-mock` 离线测试 |

```bash
npm test            # ONLINE=1 npm test 另外检查 GitHub URL
```

函数都已导出，可以在自己的代码里直接用：

```js
import { makeClient, ask, investigate } from "./src/quickstart.mjs";
const answer = await ask(makeClient(), process.env.AGENT_SPACE_ID, "us-east-1 有几个 S3 bucket？");
```

更多说明见[根目录 README](../README.md)。
