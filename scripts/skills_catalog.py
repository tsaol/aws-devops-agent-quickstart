"""Print the skills catalog (Markdown) for README.md from skills/*/SKILL.md.

  python scripts/skills_catalog.py           # print
  python scripts/skills_catalog.py --write   # replace the block between the markers in README.md
"""
import sys
import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
SHORT = {"CHAT": "Chat", "INCIDENT_TRIAGE": "Triage", "INCIDENT_RCA": "RCA", "RELEASE_TESTING": "Release testing", "GENERIC": "All"}
GROUPS = [
    ("每次调查先用", ["aws-health-events", "support-cases", "investigation-cost-guardrail"]),
    ("网络", ["aws-routing", "aws-vpc-dns-investigation", "aws-natgw-traffic-analysis"]),
    ("容器", ["aws-eks-operations-review", "eks-upgrade-readiness", "aws-eks-healthdashboard", "ecs-operation-review"]),
    ("数据库和数据", ["database-rds-devops", "rds-operation-review", "database-migration-service-expertise",
                     "redshift-support-specialist", "msk-operations", "analytics-opensearch-expertise",
                     "firehose-operation-review"]),
    ("存储和备份", ["storage-s3-resiliency-expertise", "aws-backup-coverage-review", "aws-fsxn-operations-review",
                   "storage-fsx-windows-sla-optimizer"]),
    ("AI/ML", ["bedrock-operation-review", "bedrock-adoption-readiness", "sagemaker-ai-ops-review",
                 "aiml-gpu-training-cluster-investigation", "aiml-access-diagnostics", "agentcore-ops-review",
                 "agentcore-observability-setup"]),
    ("成本", ["devops-agent-cost-insights", "cloudtrail-cost-optimization", "config-cost-optimization",
               "guardduty-cost-optimization"]),
    ("容量和大活动", ["service-quota-check", "live-streaming-event-readiness-review"]),
    ("安全", ["enrich-with-aws-security-agent", "wiz-security-context"]),
    ("第三方可观测性", ["honeycomb-production-investigation", "honeycomb-query-patterns", "honeycomb-metrics-queries",
                     "honeycomb-slos-and-triggers", "honeycomb-create-board", "honeycomb-observability-fundamentals",
                     "honeycomb-verify-recent-trace", "grafana-cloud-investigation", "sumo-logic-investigator"]),
    ("示例（先改再用）", ["skip-scheduled-maintenance", "crm-production-investigation-guidelines"]),
]
EXAMPLES = {"skip-scheduled-maintenance", "crm-production-investigation-guidelines"}
THIRD = ("honeycomb-", "grafana-", "sumo-logic-", "wiz-")


ZH = {
    "agentcore-observability-setup": "检查并补齐 Bedrock AgentCore 的可观测性，能追踪 agent 推理、发现静默失败",
    "agentcore-ops-review": "按 Well-Architected 评审 AgentCore：Runtime 韧性、Gateway、Memory、资源使用",
    "aiml-access-diagnostics": "排查 Bedrock / SageMaker 的 IAM 拒绝：逐跳查调用方、PassRole、信任策略、SCP，给出最小策略",
    "aiml-gpu-training-cluster-investigation": "排查 GPU 训练/推理集群（HyperPod、ParallelCluster、EC2/EKS GPU）",
    "analytics-opensearch-expertise": "OpenSearch 域体检：集群健康、分片、性能、安全、成本（只读）",
    "aws-backup-coverage-review": "查哪些资源没被 AWS Backup 保护，评估备份频率、保留期、跨区和跨账号复制",
    "aws-eks-healthdashboard": "EKS 集群现在健康吗：控制面、节点、工作负载一页看清",
    "aws-eks-operations-review": "按最佳实践给 EKS 集群打分：运维、安全、升级前检查、资源清单",
    "aws-fsxn-operations-review": "FSx for NetApp ONTAP 运维评审：备份、可观测性、安全等",
    "aws-health-events": "调查开头先查 AWS Health 事件（服务故障、计划变更、账号通知），判断是不是 AWS 侧问题",
    "aws-natgw-traffic-analysis": "NAT 网关里走了什么流量、为什么走这条路、怎么降低 NAT 费用",
    "aws-routing": "AWS 会选哪条路：Cloud WAN、DX Gateway、TGW 路由表、ECMP、VPC 最长前缀、BGP 流量工程",
    "aws-vpc-dns-investigation": "VPC 内域名解析不对（NXDOMAIN、SERVFAIL、解析到公网地址），或改 DNS 前做检查",
    "bedrock-adoption-readiness": "Bedrock 上生产前检查：IAM 治理、数据保留（ZDR）、配额余量、可观测性",
    "bedrock-operation-review": "按 Well-Architected 评审 Bedrock 工作负载：安全、性能、成本",
    "cloudtrail-cost-optimization": "找出并量化 CloudTrail 的省钱空间，解释费用为什么涨",
    "config-cost-optimization": "找出并量化 AWS Config 的省钱空间，解释配置项为什么暴涨",
    "crm-production-investigation-guidelines": "演示用：一个 CRM 示例应用的 triage 规则（会关闭告警合并），只作模板",
    "database-migration-service-expertise": "DMS 运维评审和排障：最佳实践、性能、成本、切换指导",
    "database-rds-devops": "Aurora MySQL / PostgreSQL 数据库内部诊断：缓冲池、连接、锁、复制、索引（需 RDS Data API）",
    "devops-agent-cost-insights": "DevOps Agent 自己花了多少钱、花在哪：按 Agent Space 和角色拆分",
    "ecs-operation-review": "ECS 运维评审：6 个维度，7 天指标基线，推荐告警阈值",
    "eks-upgrade-readiness": "EKS 升级前评估：版本偏差、废弃 API、插件兼容、升级计划",
    "enrich-with-aws-security-agent": "故障可能有安全原因时（认证失败、注入攻击等），结合 AWS Security Agent 的发现",
    "firehose-operation-review": "按 Well-Architected 评审 Amazon Data Firehose 投递流",
    "grafana-cloud-investigation": "用 Grafana Cloud 的遥测数据调查故障（需接入 Grafana Cloud）",
    "guardduty-cost-optimization": "找出并量化 GuardDuty 的省钱空间，找出贵的防护计划",
    "honeycomb-create-board": "按 SLO 和查询设计 Honeycomb 看板（需接入 Honeycomb）",
    "honeycomb-metrics-queries": "查询 Honeycomb 的 OpenTelemetry 指标数据集（需接入 Honeycomb）",
    "honeycomb-observability-fundamentals": "回答可观测性概念问题：宽事件、高基数、指标和日志的区别",
    "honeycomb-production-investigation": "用 Honeycomb 遥测找根因：延迟、错误、发布回归、依赖故障（需接入 Honeycomb）",
    "honeycomb-query-patterns": "写和读 Honeycomb 查询：百分位、热力图、关系字段（需接入 Honeycomb）",
    "honeycomb-slos-and-triggers": "解读 Honeycomb 的 SLO、错误预算消耗和触发器（需接入 Honeycomb）",
    "honeycomb-verify-recent-trace": "发布或测试后，在 Honeycomb 找到最新的 trace 并总结（需接入 Honeycomb）",
    "investigation-cost-guardrail": "调查时控制成本：调用收费 API 前先估价，限制 Athena、S3 扫描等贵操作",
    "live-streaming-event-readiness-review": "大型直播（比赛、演唱会、发布会）前的只读就绪检查：扛不扛得住峰值",
    "msk-operations": "Amazon MSK（Kafka）运维、排障和健康评估，支持 Standard 和 Express broker",
    "rds-operation-review": "按 Well-Architected 评审 RDS 和 Aurora：可用性、安全、性能、成本",
    "redshift-support-specialist": "Redshift 查询调优、运维评审和成本优化，支持预置集群和 Serverless",
    "sagemaker-ai-ops-review": "SageMaker AI 运维评审：端点、训练任务、Pipeline、Studio",
    "service-quota-check": "出现限流、LimitExceeded 时检查服务配额，也用于容量规划",
    "skip-scheduled-maintenance": "演示用：维护窗口内跳过中低优先级告警，窗口时间写死为 2025-03-15，要先改",
    "storage-fsx-windows-sla-optimizer": "FSx for Windows 的 SLA、可用性和成本评审（7 个维度）",
    "storage-s3-resiliency-expertise": "S3 存储桶的韧性、安全和数据保护评审（9 个维度）",
    "sumo-logic-investigator": "用 Sumo Logic 的日志、告警、SIEM 调查故障（需接入 Sumo Logic）",
    "support-cases": "调查开头先查历史 Support 工单，找症状相似的旧事故",
    "wiz-security-context": "资源出现异常（CPU 飙升、异常流量等）时，用 Wiz 判断是否和安全有关（需接入 Wiz）",
}


def meta(skill):
    fm = re.match(r"^---\n(.*?)\n---", (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8"), re.S).group(1)
    d = re.search(r"^description:\s*(.*?)(?=^\S|\Z)", fm, re.M | re.S).group(1)
    d = " ".join(d.replace("'", "").replace('"', "").replace(">-", "").split())
    first = re.split(r"(?<=[.])\s", d)[0]
    if len(first) > 110:
        first = first[:107].rsplit(" ", 1)[0] + "…"
    at = re.search(r"agent-types:\s*['\"]?([^'\"\n]+)", fm)
    types = [t.strip() for t in at.group(1).split(",")] if at else ["GENERIC"]
    return first, types


README = SKILLS.parent / "README.md"
START, END = "<!-- skills-catalog:start -->", "<!-- skills-catalog:end -->"


def main():
    listed = [s for _, g in GROUPS for s in g]
    actual = sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))
    assert sorted(listed) == actual, (set(actual) - set(listed), set(listed) - set(actual))
    assert sorted(ZH) == actual, set(actual) ^ set(ZH)
    out = []
    for title, group in GROUPS:
        out.append(f"<details>\n<summary><b>{title}</b>（{len(group)} 个）</summary>\n")
        out.append("| Skill | 生效于 | 做什么 |\n|---|---|---|")
        for s in group:
            _, types = meta(s)
            desc = ZH[s]
            where = ", ".join(SHORT.get(t, t) for t in types)
            note = "（示例）" if s in EXAMPLES else "（需接入）" if s.startswith(THIRD) else ""
            out.append(f"| [`{s}`](skills/{s}/){note} | {where} | {desc} |")
        out.append("\n</details>\n")
    text = "\n".join(out)
    if "--write" in sys.argv:
        r = README.read_text(encoding="utf-8")
        a, b = r.index(START) + len(START), r.index(END)
        README.write_text(r[:a] + "\n" + text + "\n" + r[b:], encoding="utf-8")
        print(f"updated {README}")
    else:
        print(text)


if __name__ == "__main__":
    main()
