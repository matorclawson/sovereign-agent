"""Engineering continuity uses scripted proposals, never a scientific-quality claim."""

import json
import signal
import subprocess
import sys
import time

import pytest

from reference_organizations.store.agent import seed_lucy
from sovereign_agent import assistant_work as queue
from sovereign_agent import research
from sovereign_agent import research_executor as executor
from sovereign_agent.database import Database
from sovereign_agent.model_turn import ModelTurn


class FixtureModel:
    def __init__(self, action="evaluate", x=0.0):
        self.calls = 0
        self.action, self.x = action, x

    def complete(self, messages, tools, **kwargs):
        self.calls += 1
        return ModelTurn(
            research.Proposal(
                action=self.action,
                x=self.x if self.action == "evaluate" else None,
                belief="Fixture hypothesis, not a conclusion",
                reason="Scripted lifecycle fixture",
                evidence=[],
            ).model_dump_json(),
            output_tokens=80,
        )


def initialized(root):
    db = research.open_agent(root)
    identifier = research.revise(db, "Which permitted point gives a lower measurement?")
    return db, identifier


def wait_for(check, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.02)
    pytest.fail("bounded fixture timed out")


def operation(db):
    return dict(db.connection.execute("SELECT * FROM research_operations").fetchone())


def receipt_path(root, op):
    return executor.directory(root, op["id"]) / "result.json"


def cli(root, *arguments):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sovereign_agent",
            "agent",
            *arguments,
            "--profile",
            "research",
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_revision_pause_resume_and_late_observation(tmp_path):
    db, identifier = initialized(tmp_path)
    model = FixtureModel()
    assert research.wake(db, tmp_path, model) == "PROPOSED"
    op = operation(db)
    research.revise(db, "Now prefer interpretation and uncertainty over another sample", identifier)
    research.control(db, identifier, "pause")
    wait_for(lambda: receipt_path(tmp_path, op).exists())
    assert research.wake(db, tmp_path, None) == "CONTROL_ONLY"
    assert model.calls == 1
    observation = [
        e for e in research.history(db, identifier) if e["kind"] == "research.observation"
    ]
    assert len(observation) == 1
    assert (observation[0]["revision"], observation[0]["current_revision"]) == (1, 2)
    assert research.reconcile(db, tmp_path) == 0  # Duplicate result is not new evidence.
    research.control(db, identifier, "resume")
    assert research.wake(db, tmp_path, FixtureModel("stop")) == "PROPOSED"
    assert research.head(db, identifier)["state"] == "STOPPED"
    assert research.context(db, identifier)["remaining"]["evaluations"] == 11
    assert cli(tmp_path, "status", "--id", identifier)["runtime"]["revision"] == 2
    assert len(cli(tmp_path, "report", "--id", identifier)) >= 8


def test_lost_ack_reuses_identity_and_stale_owner_cannot_launch(tmp_path, monkeypatch):
    db, identifier = initialized(tmp_path)
    claim = queue.claim(db, "old", role="investigation", ttl=0.05)
    original = executor.submit

    def lost_ack(root, raw):
        original(root, raw)
        raise OSError("fixture lost acknowledgement after launch")

    monkeypatch.setattr(executor, "submit", lost_ack)
    with pytest.raises(OSError):
        research.apply(
            db,
            tmp_path,
            claim,
            research.Proposal(
                action="evaluate",
                x=0.0,
                reason="fixture",
                belief="unknown",
                evidence=[],
            ),
        )
    op = operation(db)
    assert op["state"] == "INTENT"
    time.sleep(0.06)
    monkeypatch.setattr(executor, "submit", original)
    model = FixtureModel()
    assert research.wake(db, tmp_path, model, owner="replacement") == "RECOVERED"
    assert model.calls == 0
    with pytest.raises(PermissionError):
        research.launch(db, tmp_path, claim, op["request"])
    wait_for(lambda: receipt_path(tmp_path, op).exists())
    assert research.reconcile(db, tmp_path) == 1
    assert research.reconcile(db, tmp_path) == 0
    assert db.connection.execute("SELECT count(*) FROM research_operations").fetchone()[0] == 1
    assert len(list((tmp_path / ".sovereign/executor").glob("*/claimed"))) == 1
    assert research.head(db, identifier)["evaluations"] == 1


def test_redirect_revokes_even_prepared_intent_but_allows_cancel_and_collect(tmp_path):
    db, identifier = initialized(tmp_path)
    claim = queue.claim(db, "old", role="investigation")
    research.revise(db, "Do not authorize the previous experiment", identifier)
    with pytest.raises(PermissionError):
        research.apply(
            db,
            tmp_path,
            claim,
            research.Proposal(
                action="evaluate",
                x=1.0,
                reason="obsolete",
                belief="obsolete",
                evidence=[],
            ),
        )
    assert db.connection.execute("SELECT count(*) FROM research_operations").fetchone()[0] == 0
    assert research.wake(db, tmp_path, FixtureModel()) == "PROPOSED"
    op = operation(db)
    research.revise(db, "Cancel launched work and preserve its eventual receipt", identifier)
    research.cancel_operation(db, tmp_path, op["id"])
    wait_for(lambda: receipt_path(tmp_path, op).exists())
    assert research.reconcile(db, tmp_path) == 1
    assert any(
        e["kind"] == "research.cancellation_requested" for e in research.history(db, identifier)
    )


def test_unlaunched_old_intent_cannot_submit_after_redirect(tmp_path, monkeypatch):
    db, identifier = initialized(tmp_path)
    claim = queue.claim(db, "old", role="investigation")

    def unavailable(*args):
        raise OSError("fixture failed before external submission")

    monkeypatch.setattr(executor, "submit", unavailable)
    with pytest.raises(OSError):
        research.apply(
            db,
            tmp_path,
            claim,
            research.Proposal(
                action="evaluate",
                x=0.0,
                reason="fixture",
                belief="unknown",
                evidence=[],
            ),
        )
    op = operation(db)
    research.revise(db, "Changed objective", identifier)
    with pytest.raises(PermissionError):
        research.launch(db, tmp_path, claim, op["request"])
    assert not executor.directory(tmp_path, op["id"]).exists()
    # A different investigation cannot exceed the one outstanding executor lane.
    other = research.revise(db, "Another investigation")
    next_claim = queue.claim(
        db,
        "new",
        role="investigation",
        identifier=db.connection.execute(
            "SELECT work_id FROM research_work WHERE investigation=?", (other,)
        ).fetchone()[0],
    )
    with pytest.raises(PermissionError, match="existing operation"):
        research.apply(
            db,
            tmp_path,
            next_claim,
            research.Proposal(
                action="evaluate",
                x=1.0,
                reason="fixture",
                belief="unknown",
                evidence=[],
            ),
        )


@pytest.mark.parametrize("malformation", ["json", "identity", "nonfinite", "oversize"])
def test_malformed_receipts_are_preserved_and_not_observations(tmp_path, malformation):
    db, identifier = initialized(tmp_path)
    research.wake(db, tmp_path, FixtureModel())
    op = operation(db)
    path = receipt_path(tmp_path, op)
    wait_for(path.exists)
    content = json.loads(path.read_text())
    if malformation == "identity":
        content["operation"] = "different"
    elif malformation == "nonfinite":
        content["value"] = float("nan")
    raw = {"json": "{broken", "oversize": "x" * 8193}.get(malformation, json.dumps(content))
    path.write_text(raw)
    assert research.reconcile(db, tmp_path) == 0
    assert operation(db)["state"] == "MALFORMED"
    assert path.read_text() == raw
    assert not any(e["kind"] == "research.observation" for e in research.history(db, identifier))


def test_conflicting_duplicate_preserves_first_observation(tmp_path):
    db, identifier = initialized(tmp_path)
    research.wake(db, tmp_path, FixtureModel())
    op = operation(db)
    path = receipt_path(tmp_path, op)
    wait_for(path.exists)
    research.reconcile(db, tmp_path)
    original = operation(db)["receipt"]
    altered = json.loads(original)
    altered["value"] += 1
    path.write_text(json.dumps(altered))
    assert research.reconcile(db, tmp_path) == 0
    assert operation(db)["state"] == "CONFLICT"
    assert operation(db)["receipt"] == original
    assert any(e["kind"] == "research.conflicting_result" for e in research.history(db, identifier))


def test_missing_receipt_holds_unknown_without_reexecution(tmp_path, monkeypatch):
    db, identifier = initialized(tmp_path)
    monkeypatch.setattr(executor, "submit", lambda *_: None)
    assert research.wake(db, tmp_path, FixtureModel()) == "PROPOSED"
    with db.immediate() as connection:
        connection.execute("UPDATE research_operations SET submitted=?", (time.time() - 20,))
    assert research.reconcile(db, tmp_path) == 0
    assert operation(db)["state"] == "UNKNOWN"
    model = FixtureModel()
    assert research.wake(db, tmp_path, model) == "WAITING"
    assert model.calls == 0
    assert any(e["kind"] == "research.executor_unknown" for e in research.history(db, identifier))


@pytest.mark.parametrize("hard", [False, True])
def test_process_restart_collects_without_model_or_duplicate_execution(tmp_path, hard, monkeypatch):
    db, identifier = initialized(tmp_path)

    class SlowRequest(executor.Request):
        delay: float = 3.0

    monkeypatch.setattr(executor, "Request", SlowRequest)
    claim = queue.claim(db, "original", role="investigation")
    research.apply(
        db,
        tmp_path,
        claim,
        research.Proposal(
            action="evaluate",
            x=0.0,
            reason="process fixture",
            belief="unknown",
            evidence=[],
        ),
    )
    op = operation(db)
    command = [
        sys.executable,
        "-m",
        "sovereign_agent",
        "agent",
        "serve",
        "--profile",
        "research",
        "--root",
        str(tmp_path),
    ]
    log = tmp_path / "supervisor.log"
    stream = log.open("w")
    process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
    replacement = None
    try:
        wait_for(lambda: "CONTROL_ONLY" in log.read_text())
        assert not receipt_path(tmp_path, op).exists()  # Kill during the asynchronous operation.
        process.send_signal(signal.SIGKILL if hard else signal.SIGTERM)
        process.wait(timeout=5)
        assert process.returncode == (-signal.SIGKILL if hard else 0)
        replacement = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        wait_for(lambda: operation(db)["state"] == "COMPLETED")
        replacement.terminate()
        replacement.wait(timeout=5)
        assert replacement.returncode == 0
        assert operation(db)["state"] == "COMPLETED"
        assert research.head(db, identifier)["calls"] == 0
        assert len(list((tmp_path / ".sovereign/executor").glob("*/claimed"))) == 1
    finally:
        for child in (process, replacement):
            if child and child.poll() is None:
                child.kill()
                child.wait()
        stream.close()


def test_root_profile_binding_preserves_shop_and_rejects_ambiguity(tmp_path):
    shop, agent = tmp_path / "shop", tmp_path / "research"
    shop.mkdir()
    db = Database(shop / "agent.sqlite")
    seed_lucy(db)
    with pytest.raises(ValueError, match="nonempty unbound"):
        research.open_agent(shop)
    initialized(agent)
    with pytest.raises(ValueError, match="bound to the research"):
        research.check_root(agent, "shop")
    (agent / ".sovereign").mkdir(exist_ok=True)
    (agent / ".sovereign/organization.db").touch()
    with pytest.raises(ValueError, match="organization root"):
        research.open_agent(agent)
    alias = tmp_path / "alias"
    alias.mkdir()
    (alias / "actual.sqlite").touch()
    (alias / "agent.sqlite").symlink_to(alias / "actual.sqlite")
    with pytest.raises(ValueError, match="canonical file"):
        research.open_agent(alias)


def test_cli_pause_redirect_resume_and_no_organization_database(tmp_path):
    cli(tmp_path, "init")
    identifier = cli(tmp_path, "ask", "Find a low measured value")["investigation"]
    assert cli(tmp_path, "pause", "--id", identifier)["runtime"]["state"] == "PAUSED"
    cli(tmp_path, "redirect", "State uncertainty before sampling", "--id", identifier)
    assert cli(tmp_path, "status", "--id", identifier)["runtime"]["state"] == "PAUSED"
    assert cli(tmp_path, "resume", "--id", identifier)["runtime"]["state"] == "ACTIVE"
    assert not (tmp_path / ".sovereign/organization.db").exists()
    assert (tmp_path / "agent.sqlite").exists()
