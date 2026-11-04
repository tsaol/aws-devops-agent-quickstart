"""Install the official skills in tools-for-devops-agent/skills/ into an Agent Space.

  python install_skills.py list                               # skills in this repo
  python install_skills.py installed                          # skills already in the Agent Space
  python install_skills.py install aws-health-events aws-routing
  python install_skills.py install --all
  python install_skills.py install aws-routing --from-github  # Agent Space pulls it from GitHub
  python install_skills.py zip aws-routing                    # only build dist/aws-routing.zip

Env: AGENT_SPACE_ID (not needed for list / zip), AWS_REGION (default us-east-1)
Needs boto3 >= 1.43 (Asset API) and IAM: aidevops:CreateAsset, aidevops:ListAssets.
"""
import io
import os
import re
import sys
import zipfile
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent
SKILLS_DIR = ROOT / "tools-for-devops-agent" / "skills"
DIST = ROOT / "dist"
GITHUB_TREE = "https://github.com/aws/tools-for-devops-agent/tree/main/skills/"
RUNTIME_PARTS = ("SKILL.md", "references", "assets")  # what the agent reads; evals/README are dev-only
MAX_ZIP = 6 * 1024 * 1024
AGENT_TYPES = {"GENERIC", "CHAT", "INCIDENT_TRIAGE", "INCIDENT_RCA", "INCIDENT_MITIGATION",
               "INCIDENT_UI", "PREVENTION", "RELEASE_READINESS_REVIEW", "RELEASE_TESTING"}

REGION = os.environ.get("AWS_REGION", "us-east-1")
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


def installed_names():
    names, token = {}, None
    while True:
        kw = {"agentSpaceId": SPACE, "assetType": "skill", "maxResults": 50}
        if token:
            kw["nextToken"] = token
        page = client().list_assets(**kw)
        for a in page["items"]:
            names[a["metadata"].get("name")] = a["assetId"]
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
        asset = client().create_asset(
            agentSpaceId=SPACE, assetType="skill",
            metadata={"agent_types": fm["agent_types"]}, content=content,
        )["asset"]
        print(f"install {s} -> {asset['assetId']} {fm['agent_types']}")
        results[s] = asset["assetId"]
    return results


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "list":
        for s in all_skills():
            print(f"{s:45} {','.join(frontmatter(s)['agent_types'])}")
        return
    if cmd == "zip":
        DIST.mkdir(exist_ok=True)
        for s in args or all_skills():
            out = DIST / f"{s}.zip"
            out.write_bytes(build_zip(s))
            print(f"{out}  {out.stat().st_size // 1024} KB")
        return
    if not SPACE:
        sys.exit("set AGENT_SPACE_ID first")
    if cmd == "installed":
        for name, aid in sorted(installed_names().items()):
            print(f"{name:45} {aid}")
    elif cmd == "install":
        github = "--from-github" in args
        names = [a for a in args if not a.startswith("--")]
        skills = all_skills() if "--all" in args else names
        unknown = set(skills) - set(all_skills())
        if not skills or unknown:
            sys.exit(f"unknown skills: {sorted(unknown)}" if unknown else __doc__)
        install(skills, from_github=github)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
