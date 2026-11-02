"""Checks the Pages workflow keeps the three protections it was written for (2026-11-02).

Run: python .github/tests/test_pages_workflow.py   (needs PyYAML; exits non-zero on a failure)

.github/ is excluded from the published site, so nothing here is served.
"""
import pathlib
import sys

import yaml

WF = pathlib.Path(__file__).resolve().parents[1] / "workflows" / "pages.yml"


def load():
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on` as the boolean True.
    if True in doc:
        doc["on"] = doc.pop(True)
    return doc


def steps(doc):
    return doc["jobs"]["publish"]["steps"]


def test_triggers_on_main_push_and_manual():
    on = load()["on"]
    assert on["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in on


def test_queues_instead_of_cancelling():
    # Nov 1 failed because a second deploy started while the first was still in progress.
    c = load()["concurrency"]
    assert c["group"] == "pages"
    assert c["cancel-in-progress"] is False


def test_permissions_are_the_minimum_pages_needs():
    assert load()["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}


def test_hung_job_times_out():
    # Oct 31's build hung 45 minutes; three deploy attempts plus waits fit well inside 25.
    assert 0 < load()["jobs"]["publish"]["timeout-minutes"] <= 30


def test_publishes_the_same_files_as_before():
    upload = [s for s in steps(load()) if "upload-pages-artifact" in s.get("uses", "")]
    assert len(upload) == 1
    assert upload[0]["with"]["path"] == "."
    # v3 keeps dotfiles such as .nojekyll in the artifact; later majors drop hidden files by default.
    assert upload[0]["uses"].endswith("@v3")


def test_deploy_retries_twice_and_last_attempt_can_fail_the_run():
    st = steps(load())
    deploys = [s for s in st if "deploy-pages" in s.get("uses", "")]
    assert [d["id"] for d in deploys] == ["deploy1", "deploy2", "deploy3"]
    assert deploys[0].get("continue-on-error") is True and "if" not in deploys[0]
    assert deploys[1]["if"] == "steps.deploy1.outcome == 'failure'"
    assert deploys[1].get("continue-on-error") is True
    assert deploys[2]["if"] == "steps.deploy2.outcome == 'failure'"
    # The last attempt must NOT swallow its error, or a real outage would show as a green run.
    assert not deploys[2].get("continue-on-error", False)
    waits = [s for s in st if s.get("run", "").startswith("sleep")]
    assert [w["if"] for w in waits] == [deploys[1]["if"], deploys[2]["if"]]


def test_checkout_does_not_keep_credentials():
    co = [s for s in steps(load()) if s.get("uses", "").startswith("actions/checkout@")]
    assert co and co[0]["with"]["persist-credentials"] is False


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except AssertionError as e:
                failed += 1
                print("FAIL", name, e)
    sys.exit(1 if failed else 0)
