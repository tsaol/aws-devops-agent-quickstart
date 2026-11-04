# 来源

这个目录是官方仓库 [aws/tools-for-devops-agent](https://github.com/aws/tools-for-devops-agent) 的完整副本，没有改动。

- 来源 commit：`b807b0368b6d24333c6ad5989a5543dc010dbeff`（2026-11-04）
- License：Apache-2.0，见本目录的 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)，Copyright Amazon.com, Inc. or its affiliates
- 官方说明：这些是 sample code，上生产前请先在非生产环境测试，并检查 IAM 权限
- 最新版本请以官方仓库为准

更新方法：

```bash
git clone --depth 1 https://github.com/aws/tools-for-devops-agent.git /tmp/tfda
rsync -a --delete --exclude=.git --exclude=UPSTREAM.md /tmp/tfda/ tools-for-devops-agent/
```
