"""Install the official skills in tools-for-devops-agent/skills/ into an Agent Space.

  python install_skills.py list                               # skills in this repo
  python install_skills.py installed                          # skills already in the Agent Space
  python install_skills.py install aws-health-events aws-routing
  python install_skills.py install --all                      # skips examples and third-party skills
  python install_skills.py install --all --include-examples --include-third-party
  python install_skills.py install aws-routing --from-github  # Agent Space pulls it from GitHub
  python install_skills.py zip aws-routing                    # only build dist/aws-routing.zip

Env: AGENT_SPACE_ID (not needed for list / zip)
     AWS_REGION, else AWS_DEFAULT_REGION, else us-east-1
Needs boto3 >= 1.43 (Asset API) and IAM: aidevops:CreateAsset, aidevops:ListAssets.
"""
import io
import os
import re
import sys
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

HERE = Path(__file__).resolve().parent   # python/
ROOT = HERE.parent                       # repo root
SKILLS_DIR = ROOT / "tools-for-devops-agent" / "skills"
DIST = HERE / "dist"
GITHUB_TREE = "https://github.com/aws/tools-for-devops-agent/tree/main/skills/"
RUNTIME_PARTS = ("SKILL.md", "references", "assets")  # what the agent reads; evals/README are dev-only
MAX_ZIP = 6 * 1024 * 1024
AGENT_TYPES = {"GENERIC", "CHAT", "INCIDENT_TRIAGE", "INCIDENT_RCA", "INCIDENT_MITIGATION",
               "INCIDENT_UI", "PREVENTION", "RELEASE_READINESS_REVIEW", "RELEASE_TESTING"}

# --all skips these unless asked. You can still install them by name.
EXAMPLES = {  # demo rules, edit before real use
    "crm-production-investigation-guidelines",  # triage rules for a demo CRM app; turns off incident linking
    "skip-scheduled-maintenance",               # fixed sample window 2025-03-15
}
THIRD_PARTY_PREFIXES = ("honeycomb-", "grafana-", "sumo-logic-", "wiz-")  # need that tool connected first

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
SPACE = os.environ.get("AGENT_SPACE_ID", "")
_client = None


def client():
    global _client
    if _client is None:
        _client = boto3.client("devops-agent", region_name=REGION)
    return _client


def frontmatter(skill):
    """name, description and agent types from SKILL.md."""
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        raise ValueError(f"{skill}: SKILL.md has no frontmatter")
    fm = m.group(1)
    name = re.search(r"^name:\s*['\"]?([\w-]+)", fm, re.M).group(1)
    at = re.search(r"aws-devops-agent-skills\.agent-types:\s*['\"]?([^'\"\n]+)", fm)
    types = [t.strip() for t in at.group(1).split(",")] if at else ["GENERIC"]
    bad = set(types) - AGENT_TYPES
    if bad:
        raise ValueError(f"{skill}: unknown agent types {bad}")
    return {"name": name, "agent_types": types}


def all_skills():
    return sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))


def build_zip(skill):
    """Zip only SKILL.md, references/ and assets/, with SKILL.md at the zip root."""
    if skill not in all_skills():
        raise ValueError(f"unknown skill: {skill}")
    src = SKILLS_DIR / skill
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for part in RUNTIME_PARTS:
            p = src / part
            files = [p] if p.is_file() else sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else []
            for f in files:
                z.write(f, f.relative_to(src).as_posix())
    data = buf.getvalue()
    if len(data) > MAX_ZIP:
        raise ValueError(f"{skill}: zip is {len(data)} bytes, over the 6 MB limit")
    return data


def default_skills(include_examples=False, include_third_party=False):
    out = []
    for s in all_skills():
        if s in EXAMPLES and not include_examples:
            continue
        if s.startswith(THIRD_PARTY_PREFIXES) and not include_third_party:
            continue
        out.append(s)
    return out


def installed_names():
    names, token = {}, None
    while True:
        kw = {"agentSpaceId": SPACE, "assetType": "skill", "maxResults": 50}
        if token:
            kw["nextToken"] = token
        page = client().list_assets(**kw)
        for a in page["items"]:
            name = (a.get("metadata") or {}).get("name")
            if name:
                names[name] = a["assetId"]
        token = page.get("nextToken")
        if not token:
            return names


def install(skills, from_github=False):
    have = installed_names()
    results = {}
    for s in skills:
        fm = frontmatter(s)
        if fm["name"] in have:
            print(f"skip    {s} (already installed: {have[fm['name']]})")
            results[s] = "skipped"
            continue
        if from_github:
            content = {"sourceUrl": {"url": GITHUB_TREE + s}}
        else:
            content = {"zip": {"zipFile": build_zip(s)}}  # boto3 base64-encodes blobs
        try:
            asset = client().create_asset(
                agentSpaceId=SPACE, assetType="skill",
                metadata={"agent_types": fm["agent_types"]}, content=content,
            )["asset"]
        except ClientError as e:  # e.g. --from-github without a GitHub association
            msg = e.response["Error"].get("Message", str(e))
            print(f"FAILED  {s}: {e.response['Error']['Code']}: {msg}")
            results[s] = "failed"
            continue
        print(f"install {s} -> {asset['assetId']} {','.join(fm['agent_types'])}")
        results[s] = asset["assetId"]
    return results


FLAGS = {"--all", "--from-github", "--include-examples", "--include-third-party"}


def usage(msg=None):
    if msg:
        print(msg, file=sys.stderr)
    print(__doc__, file=sys.stderr)
    sys.exit(2)


def main(argv):
    if not argv:
        usage()
    cmd, args = argv[0], argv[1:]
    flags = [a for a in args if a.startswith("--")]
    names = [a for a in args if not a.startswith("--")]
    bad = sorted(set(flags) - FLAGS) if cmd == "install" else flags
    if bad:
        usage(f"unknown option: {' '.join(bad)}")
    unknown = sorted(set(names) - set(all_skills()))
    if unknown and cmd in ("zip", "install"):
        usage(f"unknown skills: {', '.join(unknown)} (see: python install_skills.py list)")

    if cmd == "list":
        for s in all_skills():
            tag = " (example)" if s in EXAMPLES else " (third-party)" if s.startswith(THIRD_PARTY_PREFIXES) else ""
            print(f"{s:45} {','.join(frontmatter(s)['agent_types'])}{tag}")
        return
    if cmd == "zip":
        DIST.mkdir(exist_ok=True)
        for s in names or all_skills():
            out = DIST / f"{s}.zip"
            out.write_bytes(build_zip(s))
            print(f"{out}  {out.stat().st_size // 1024} KB")
        return
    if cmd not in ("installed", "install"):
        usage()
    if not SPACE:
        usage("set AGENT_SPACE_ID first")
    if cmd == "installed":
        for name, aid in sorted(installed_names().items()):
            print(f"{name:45} {aid}")
        return
    if "--all" in flags:
        if names:
            usage("use either --all or skill names, not both")
        skills = default_skills("--include-examples" in flags, "--include-third-party" in flags)
        skipped = sorted(set(all_skills()) - set(skills))
        if skipped:
            print(f"--all skips {len(skipped)} (examples / third-party): {', '.join(skipped)}")
    else:
        skills = names
    if not skills:
        usage("name skills or use --all")
    results = install(skills, from_github="--from-github" in flags)
    if "failed" in results.values():
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
