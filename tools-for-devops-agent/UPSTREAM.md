# 来源

这个目录是官方仓库 [aws/tools-for-devops-agent](https://github.com/aws/tools-for-devops-agent) 的副本，文件内容没有改动。

**唯一的结构调整**：官方的 `skills/` 目录移到了本仓库根目录的 [`../skills/`](../skills/)，方便查找。所以本目录里文档指向 `skills/` 的相对链接会失效，请到根目录的 `skills/` 找，或看[官方 Skills 目录](https://aws.github.io/tools-for-devops-agent/skills/)。

- 来源 commit：`b807b0368b6d24333c6ad5989a5543dc010dbeff`（2026-11-04）
- License：Apache-2.0，见本目录的 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)，Copyright Amazon.com, Inc. or its affiliates
- 官方说明：这些是 sample code，上生产前请先在非生产环境测试，并检查 IAM 权限
- 最新版本请以官方仓库为准

更新方法：

```bash
git clone --depth 1 https://github.com/aws/tools-for-devops-agent.git /tmp/tfda
rsync -a --delete --exclude=.git --exclude=UPSTREAM.md --exclude=skills /tmp/tfda/ tools-for-devops-agent/
rsync -a --delete --exclude=README.md --exclude=LICENSE --exclude=NOTICE /tmp/tfda/skills/ skills/
```
