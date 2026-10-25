"""Persistent investigations, explicit campaign renewal and honest usage exposure."""

import json
import subprocess
import sys
import time

import pytest

from sovereign_agent import assistant_work as queue
from sovereign_agent import database, research
from sovereign_agent import research_allowance as allowance
from sovereign_agent.events import append_event
from tests.test_research_continuity import FixtureModel, wait_for


def command(root, *args):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sovereign_agent",
            "agent",
            *args,
            "--profile",
            "research",
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_later_campaign_continues_same_investigation_across_processes(tmp_path):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Compare measurements; preserve uncertain interpretations")
    assert research.wake(db, tmp_path, FixtureModel()) == "PROPOSED"
    wait_for(lambda: research.reconcile(db, tmp_path) == 1)
    before = research.head(db, identifier)
    original = allowance.current(db, identifier)
    with db.immediate() as connection:
        connection.execute("UPDATE research_campaigns SET deadline=?", (time.time() - 86400,))
    assert command(tmp_path, "work").returncode == 0
    assert research.head(db, identifier)["state"] == "WAITING_ALLOWANCE"
    assert command(tmp_path, "resume", "--id", identifier).returncode != 0
    assert (
        command(
            tmp_path,
            "allow",
            "--id",
            identifier,
            "--key",
            "later-session",
            "--evidence",
            "operator fixture authorization",
            "--campaign-calls",
            "3",
        ).returncode
        == 0
    )
    assert command(tmp_path, "resume", "--id", identifier).returncode == 0
    assert research.wake(db, tmp_path, FixtureModel("interpret")) == "PROPOSED"
    after = research.head(db, identifier)
    assert after["evaluations"] == before["evaluations"] == 1
    assert after["calls"] == before["calls"] + 1 == 2
    assert after["tokens"] == before["tokens"] + 80 == 160
    assert db.connection.execute("SELECT count(*) FROM investigations").fetchone()[0] == 1
    history = research.history(db, identifier)
    assert any(e["kind"] == "research.observation" for e in history)
    assert len([e for e in history if e["kind"] == "research.proposal"]) == 2
    campaigns = allowance.status(db, identifier)["campaigns"]
    assert campaigns[0]["id"] == original["id"] and campaigns[0]["state"] == "EXPIRED"
    assert campaigns[1]["id"] == "later-session" and campaigns[1]["calls"] == 1


def test_repeated_grant_and_cumulative_ceiling_never_reset_accounting(tmp_path):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Question persists")
    with db.immediate():
        allowance.grant(db, identifier, "once", 10, "operator")
    original = allowance.current(db, identifier)
    with db.immediate():
        allowance.grant(db, identifier, "once", 600, "operator")
    assert allowance.current(db, identifier)["deadline"] == original["deadline"]
    with db.immediate() as connection:
        connection.execute("UPDATE investigations SET calls=12 WHERE id=?", (identifier,))
    with pytest.raises(PermissionError, match="cumulative"):
        with db.immediate():
            allowance.grant(db, identifier, "new", 600, "operator")
    assert research.head(db, identifier)["calls"] == 12


def test_legacy_failed_preflight_is_unknown_until_explicit_evidenced_release(tmp_path, monkeypatch):
    migrations = database.MIGRATIONS
    monkeypatch.setattr(database, "MIGRATIONS", migrations[:-1])
    old = database.Database(tmp_path / "agent.sqlite")
    with old.immediate() as connection:
        connection.execute("INSERT INTO research_profile(id) VALUES(1)")
        connection.execute("INSERT INTO outcomes VALUES ('investigation','{}')")
        connection.execute(
            "INSERT INTO investigations(id,revision,deadline,calls,tokens) "
            "VALUES ('investigation',1,0,1,1000)"
        )
        work = queue._enqueue(
            connection, "old", "investigation", "question", time.time(), role="investigation"
        )
        connection.execute("INSERT INTO research_work VALUES (?, 'investigation',1)", (work,))
        append_event(
            old,
            "research.inference_reserved",
            {"investigation": "investigation", "work": work, "output_allowance": 1000},
        )
    old.connection.close()
    monkeypatch.setattr(database, "MIGRATIONS", migrations)
    db = research.open_agent(tmp_path)
    status = allowance.status(db, "investigation")
    assert status["unknown"] == 1000 and status["released"] == 0
    reservation = status["inference"][0]["id"]
    result = command(
        tmp_path,
        "release-inference",
        "no-inference",
        "--key",
        reservation,
        "--evidence",
        "preserved preflight stderr: client rejected argument before inference",
    )
    assert result.returncode == 0, result.stderr
    status = allowance.status(db, "investigation")
    assert status["unknown"] == 0 and status["released"] == 1000
    assert research.head(db, "investigation")["calls"] == 1
    assert research.head(db, "investigation")["tokens"] == 0
    assert any(
        e["kind"] == "research.inference_reserved" for e in research.history(db, "investigation")
    )


def test_stale_inference_and_undispatched_intent_have_supported_recovery(tmp_path, monkeypatch):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Research objective")
    claim = queue.claim(db, "old", role="investigation")

    def failed(*args):
        raise OSError("fixture failed before submit")

    monkeypatch.setattr(research.executor, "submit", failed)
    with pytest.raises(OSError):
        research.apply(
            db,
            tmp_path,
            claim,
            research.Proposal(
                action="evaluate", x=0.0, belief="unknown", reason="fixture", evidence=[]
            ),
        )
    operation = db.connection.execute("SELECT id FROM research_operations").fetchone()[0]
    assert "recover" in json.dumps(research.context(db, identifier)["recovery"])
    assert (
        command(
            tmp_path,
            "recover",
            "--key",
            operation,
            "--evidence",
            "operator verified no request or claim",
        ).returncode
        == 0
    )
    assert (
        db.connection.execute("SELECT state FROM research_operations").fetchone()[0] == "WITHDRAWN"
    )
    with pytest.raises(PermissionError):
        research.launch(db, tmp_path, claim, "{}")
    with db.immediate() as connection:
        connection.execute(
            "UPDATE research_profile SET inference_owner='abandoned',inference_until=0"
        )
    assert "stale inference" in json.dumps(research.context(db, identifier)["recovery"])
    assert command(tmp_path, "work").returncode == 0
    assert db.connection.execute("SELECT inference_owner FROM research_profile").fetchone()[0] == ""


@pytest.mark.parametrize("resource", ["actions", "evaluations"])
def test_campaign_resource_exhaustion_rejects_without_reset(tmp_path, resource):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Keep measurements and accounting")
    limits = dict(allowance.CAPS, **{resource: 1})
    with db.immediate():
        campaign = allowance.grant(db, identifier, "bounded", 600, "operator", limits)
        allowance.charge(db, identifier, campaign, resource, 1)
    with pytest.raises(PermissionError, match=resource):
        with db.immediate():
            allowance.charge(db, identifier, campaign, resource, 1)
    assert research.head(db, identifier)[resource] == 1
    with db.immediate():
        allowance.grant(db, identifier, "later", 600, "operator", limits)
    assert research.head(db, identifier)[resource] == 1


@pytest.mark.parametrize(
    "change", [{"calls": 13}, {"tokens": 0}, {"actions": -1}, {"evaluations": 13}, {"calls": True}]
)
def test_invalid_campaign_limits_preserve_current_authority(tmp_path, change):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Bounded objective")
    original = allowance.current(db, identifier)
    with pytest.raises(ValueError, match="bounded campaign"):
        with db.immediate():
            allowance.grant(
                db, identifier, "invalid", 600, "operator", dict(allowance.CAPS, **change)
            )
    assert allowance.current(db, identifier) == original


def test_private_research_state_and_proposal_permissions(tmp_path):
    tmp_path.chmod(0o755)
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Private fixture")
    assert research.wake(db, tmp_path, FixtureModel()) == "PROPOSED"
    wait_for(lambda: research.reconcile(db, tmp_path) == 1)
    assert tmp_path.stat().st_mode & 0o777 == 0o700
    assert db.path.stat().st_mode & 0o777 == 0o600
    proposals = list(tmp_path.glob(".sovereign/runs/*/proposal.json"))
    assert len(proposals) == 1
    assert proposals[0].stat().st_mode & 0o777 == 0o600
    assert research.head(db, identifier)["evaluations"] == 1


@pytest.mark.parametrize("resource", ["actions", "evaluations"])
def test_lifetime_action_evaluation_ceiling_survives_campaign_change(tmp_path, resource):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Retain lifetime accounting")
    with db.immediate() as connection:
        connection.execute(
            f"UPDATE investigations SET {resource}=? WHERE id=?",
            (allowance.CAPS[resource] - 1, identifier),
        )
        campaign = allowance.grant(db, identifier, "last-unit", 600, "operator")
        allowance.charge(db, identifier, campaign, resource, 1)
    if resource == "actions":
        with pytest.raises(PermissionError, match="cumulative"):
            with db.immediate():
                allowance.grant(db, identifier, "later", 600, "operator")
    else:
        with db.immediate():
            later = allowance.grant(db, identifier, "later", 600, "operator")
        assert allowance.current(db, identifier)["evaluation_limit"] == 0
        with pytest.raises(PermissionError, match="evaluations"):
            with db.immediate():
                allowance.charge(db, identifier, later, resource, 1)
    assert research.head(db, identifier)[resource] == allowance.CAPS[resource]


@pytest.mark.parametrize("seconds", [0, 601, True])
def test_invalid_campaign_clock_does_not_replace_authority(tmp_path, seconds):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Do not renew on invalid input")
    before = allowance.current(db, identifier)
    with pytest.raises(ValueError, match="bounded campaign"):
        with db.immediate():
            allowance.grant(db, identifier, "invalid-clock", seconds, "operator")
    assert allowance.current(db, identifier) == before
