"""5.7 Usage this month and service quotas.

  python s57_usage_and_quotas.py            # usage hours + quotas
  python s57_usage_and_quotas.py --usage    # only usage (needs no Service Quotas permission)

IAM: aidevops:GetAccountUsage
     servicequotas:ListServices, servicequotas:ListServiceQuotas,
     servicequotas:ListAWSDefaultServiceQuotas (for the quota part)
"""
import argparse

import boto3
from botocore.exceptions import ClientError

from common import REGION, client, error_code

# get_account_usage fields -> what they count. All values are HOURS, per account, this month.
USAGE = {
    "monthlyAccountInvestigationHours": "调查 investigation",
    "monthlyAccountEvaluationHours": "预防评估 evaluation",
    "monthlyAccountOnDemandHours": "问答 on-demand chat",
    "monthlyAccountSystemLearningHours": "系统学习 system learning",
    "monthlyAccountGraderHours": "调查评审 grader",
}


def usage():
    """get_account_usage(): no parameters, account level (all Agent Spaces in the Region).
    Each field is {"usage": hours used, "limit": monthly limit, -1 = no limit}.
    usagePeriodStartTime / usagePeriodEndTime: the current month so far."""
    return client.get_account_usage()


def quotas(region=REGION):
    """Quotas live in Service Quotas, not in the devops-agent API.

    1. list_services -> find the DevOps Agent service code by name
    2. list_service_quotas -> values applied to this account (after any increase)
    3. list_aws_default_service_quotas -> defaults, for quotas never changed
    Adjustable quotas can be raised with request_service_quota_increase.
    """
    sq = boto3.client("service-quotas", region_name=region)
    services = [s for page in sq.get_paginator("list_services").paginate() for s in page["Services"]
                if "devops agent" in s["ServiceName"].lower()]
    out = []
    for s in services:
        code = s["ServiceCode"]
        applied = {q["QuotaCode"]: q for page in sq.get_paginator("list_service_quotas").paginate(ServiceCode=code)
                   for q in page["Quotas"]}
        for page in sq.get_paginator("list_aws_default_service_quotas").paginate(ServiceCode=code):
            for q in page["Quotas"]:
                q = applied.get(q["QuotaCode"], q)
                out.append((code, q["QuotaCode"], q["QuotaName"], q["Value"], q["Adjustable"]))
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--usage", action="store_true", help="only show usage")
    a = p.parse_args()

    u = usage()
    print(f"usage {u['usagePeriodStartTime']:%Y-%m-%d} .. {u['usagePeriodEndTime']:%Y-%m-%d %H:%M} (hours, whole account)")
    for field, label in USAGE.items():
        if field in u:
            v = u[field]
            limit = "no limit" if v["limit"] < 0 else f"of {v['limit']}"
            print(f"  {label:28} {v['usage']:8.2f} h  {limit}")

    if not a.usage:
        print("\nquotas (Service Quotas)")
        try:
            rows = quotas()
            if not rows:
                print("  DevOps Agent not found in Service Quotas for this Region")
            for code, qcode, name, value, adjustable in rows:
                print(f"  {name:55} {value:>8g}  {'adjustable' if adjustable else 'fixed'}  ({code}/{qcode})")
            if rows:
                print("\n  raise one: aws service-quotas request-service-quota-increase "
                      "--service-code <code> --quota-code <quotaCode> --desired-value <n>")
        except ClientError as e:
            print(f"  {error_code(e)}\n  grant servicequotas:ListServices / ListServiceQuotas / "
                  "ListAWSDefaultServiceQuotas, or see the quota table in the user guide (Quotas page)")
