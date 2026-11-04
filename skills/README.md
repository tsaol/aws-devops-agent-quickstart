# 官方 Skills（47 个）

这里是 [aws/tools-for-devops-agent](https://github.com/aws/tools-for-devops-agent) 仓库 `skills/` 目录的副本，内容没有改动，来源 commit 见 [`../tools-for-devops-agent/UPSTREAM.md`](../tools-for-devops-agent/UPSTREAM.md)。License：Apache-2.0，见本目录的 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。

每个子目录是一个 skill：

```
skills/<skill-name>/
├── SKILL.md       Agent 运行时读：frontmatter（name、description、agent-types）+ 排查步骤
├── references/    Agent 运行时读：补充资料（可选）
├── assets/        Agent 运行时读：图片、数据文件（可选）
├── README.md      给人看：前置条件、需要的 IAM 权限、示例问题
├── CHANGELOG.md   版本记录
└── evals/         评测数据（开发用）
```

怎么装进 Agent Space、先装哪些、全部 47 个的说明，见[根目录 README](../README.md#官方-skills)。
