"""Tests for install_skills.py.

  python tests/test_install_skills.py            # offline checks + Stubber flow
  python tests/test_install_skills.py --online   # also open every GitHub skill URL

Stubber checks each request against the real devops-agent API model (boto3 >= 1.43),
so a wrong operation name, a missing required field or a bad type fails here.
"""
import datetime as dt
import io
import os
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # python/
ROOT = HERE.parent                               # repo root
os.environ["AGENT_SPACE_ID"] = "00000000-0000-0000-0000-000000000000"
os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
sys.path.insert(0, str(HERE))

from botocore.stub import ANY, Stubber  # noqa: E402

import install_skills as ins  # noqa: E402

S = os.environ["AGENT_SPACE_ID"]
NOW = dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc)


def asset(aid, name):
    return {"assetId": aid, "assetType": "skill", "metadata": {"name": name},
            "version": 1, "createdAt": NOW, "updatedAt": NOW}


def test_frontmatter():
    skills = ins.all_skills()
    assert len(skills) == 47, len(skills)
    for s in skills:
        fm = ins.frontmatter(s)
        assert fm["name"] == s, (s, fm)
        assert fm["agent_types"] and set(fm["agent_types"]) <= ins.AGENT_TYPES, (s, fm)
        assert "GENERIC" not in fm["agent_types"] or fm["agent_types"] == ["GENERIC"], s
    print(f"ok  frontmatter: {len(skills)} skills, all agent types valid")


def test_zips():
    biggest = 0
    for s in ins.all_skills():
        data = ins.build_zip(s)
        biggest = max(biggest, len(data))
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        assert "SKILL.md" in names, (s, names[:5])
        for n in names:
            top = n.split("/")[0]
            assert top in ins.RUNTIME_PARTS, (s, n)  # no evals/, README.md, CHANGELOG.md, scripts/
    assert biggest < ins.MAX_ZIP
    print(f"ok  zips: all 47 build, SKILL.md at root, only runtime files, biggest {biggest // 1024} KB")


def test_default_selection():
    d = ins.default_skills()
    assert len(d) == 35, len(d)
    assert not set(d) & ins.EXAMPLES
    assert not [x for x in d if x.startswith(ins.THIRD_PARTY_PREFIXES)]
    assert len(ins.default_skills(include_examples=True)) == 37
    assert len(ins.default_skills(include_examples=True, include_third_party=True)) == 47
    print("ok  --all: 35 by default, skips 2 examples + 10 third-party, flags add them back")


def test_readme_lists_every_skill():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [s for s in ins.all_skills() if f"`{s}`" not in readme]
    assert not missing, missing
    print("ok  README: all 47 skills listed")


def test_install_flow():
    st = Stubber(ins.client())
    # one skill already in the Agent Space, on the second page
    st.add_response("list_assets", {"items": [asset("a-0", "some-other-skill")], "nextToken": "p2"},
                    {"agentSpaceId": S, "assetType": "skill", "maxResults": 50})
    st.add_response("list_assets", {"items": [asset("a-1", "aws-health-events")]},
                    {"agentSpaceId": S, "assetType": "skill", "maxResults": 50, "nextToken": "p2"})
    st.add_response("create_asset", {"asset": asset("a-2", "aws-routing")}, {
        "agentSpaceId": S, "assetType": "skill",
        "metadata": {"agent_types": ["CHAT", "INCIDENT_RCA"]},
        "content": {"zip": {"zipFile": ANY}}})
    st.add_response("list_assets", {"items": []},
                    {"agentSpaceId": S, "assetType": "skill", "maxResults": 50})
    st.add_response("create_asset", {"asset": asset("a-3", "skip-scheduled-maintenance")}, {
        "agentSpaceId": S, "assetType": "skill",
        "metadata": {"agent_types": ["INCIDENT_TRIAGE"]},
        "content": {"sourceUrl": {"url": ins.GITHUB_TREE + "skip-scheduled-maintenance"}}})
    st.add_response("list_assets", {"items": []},
                    {"agentSpaceId": S, "assetType": "skill", "maxResults": 50})
    st.add_client_error("create_asset", "ValidationException",
                        "No GitHub access is configured for the repository's host.")
    st.add_response("create_asset", {"asset": asset("a-4", "support-cases")}, {
        "agentSpaceId": S, "assetType": "skill",
        "metadata": {"agent_types": ["CHAT", "INCIDENT_RCA"]},
        "content": {"sourceUrl": {"url": ins.GITHUB_TREE + "support-cases"}}})
    with st:
        r = ins.install(["aws-health-events", "aws-routing"])
        assert r == {"aws-health-events": "skipped", "aws-routing": "a-2"}, r
        r = ins.install(["skip-scheduled-maintenance"], from_github=True)
        assert r == {"skip-scheduled-maintenance": "a-3"}, r
        r = ins.install(["aws-routing", "support-cases"], from_github=True)  # first fails, second still runs
        assert r == {"aws-routing": "failed", "support-cases": "a-4"}, r
        st.assert_no_pending_responses()
    print("ok  install flow: skip existing, zip upload, GitHub import, keep going after a failure (Stubber vs API model)")


def test_cli():
    py = sys.executable
    env = {**os.environ, "AGENT_SPACE_ID": ""}
    out = subprocess.run([py, "install_skills.py", "list"], cwd=HERE, env=env,
                         capture_output=True, text=True, check=True).stdout
    assert out.count("\n") == 47 and "aws-routing" in out, out[:300]
    out = subprocess.run([py, "install_skills.py", "zip", "aws-routing"], cwd=HERE, env=env,
                         capture_output=True, text=True, check=True).stdout
    z = HERE / "dist" / "aws-routing.zip"
    assert z.exists() and "aws-routing.zip" in out
    z.unlink()
    (HERE / "dist").rmdir()
    r = subprocess.run([py, "install_skills.py", "install", "aws-routing"], cwd=HERE, env=env,
                       capture_output=True, text=True)
    assert r.returncode != 0 and "AGENT_SPACE_ID" in r.stderr, r.stderr
    print("ok  cli: list, zip, and install refuses without AGENT_SPACE_ID")


def test_github_urls():
    bad = []
    for s in ins.all_skills():
        url = ins.GITHUB_TREE + s
        try:
            code = urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=20).status
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "code", str(e))
        if code != 200:
            bad.append((s, code))
    assert not bad, bad
    print("ok  github: all 47 skill URLs open (HTTP 200)")


if __name__ == "__main__":
    test_frontmatter()
    test_zips()
    test_default_selection()
    test_readme_lists_every_skill()
    test_install_flow()
    test_cli()
    if "--online" in sys.argv:
        test_github_urls()
    print("ALL OK")
