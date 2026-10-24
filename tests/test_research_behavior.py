"""Proposal/budget controls, not evidence of model-driven scientific competence."""

import json
import time

import pytest

from sovereign_agent import research
from sovereign_agent.model_turn import ModelError, ModelTurn


class Reply:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def complete(self, messages, tools, **kwargs):
        self.calls += 1
        if isinstance(self.text, Exception):
            raise self.text
        return ModelTurn(self.text, output_tokens=20)


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        '{"action":"run_shell"}',
        ModelError("fixture timeout"),
        json.dumps(
            {
                "action": "interpret",
                "reason": "invented citation",
                "belief": "certain",
                "evidence": ["nonexistent"],
            }
        ),
    ],
)
def test_invalid_proposals_hold_without_scientific_effect(tmp_path, text):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Find a bounded low value")
    model = Reply(text)
    assert research.wake(db, tmp_path, model) == "HELD"
    assert model.calls == 1
    assert research.head(db, identifier)["evaluations"] == 0
    assert research.head(db, identifier)["calls"] == 1
    assert research.head(db, identifier)["tokens"] == 1000  # Lost output stays reserved.
    assert research.wake(db, tmp_path, model) == "WAITING"
    assert model.calls == 1


@pytest.mark.parametrize("budget,value", [("calls", 12), ("tokens", 12000), ("deadline", 0)])
def test_exhausted_budget_never_calls_model(tmp_path, budget, value):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Bounded question")
    with db.immediate() as connection:
        connection.execute(f"UPDATE investigations SET {budget}=? WHERE id=?", (value, identifier))
    model = Reply("never called")
    assert research.wake(db, tmp_path, model) == "HELD"
    assert model.calls == 0


def test_wait_and_operator_pause_require_no_inference(tmp_path):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Wait for a permitted later wake")
    model = Reply(
        research.Proposal(
            action="wait", reason="bounded timer", belief="uncertain", evidence=[], wait_seconds=60
        ).model_dump_json()
    )
    assert research.wake(db, tmp_path, model) == "PROPOSED"
    for _ in range(3):
        assert research.wake(db, tmp_path, model) == "WAITING"
    assert model.calls == 1
    assert research.head(db, identifier)["next_due"] > time.time()
    research.control(db, identifier, "pause")
    assert research.wake(db, tmp_path, model) == "WAITING"
    assert model.calls == 1


def test_redirect_during_model_turn_rejects_old_proposal(tmp_path):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Old question")

    class RedirectingModel:
        def complete(self, *args, **kwargs):
            research.revise(db, "New question", identifier)
            return ModelTurn(
                research.Proposal(
                    action="evaluate",
                    x=0.0,
                    evidence=[],
                    reason="obsolete answer",
                    belief="obsolete",
                ).model_dump_json(),
                output_tokens=10,
            )

    assert research.wake(db, tmp_path, RedirectingModel()) == "HELD"
    assert research.head(db, identifier)["revision"] == 2
    assert research.head(db, identifier)["evaluations"] == 0


def test_redirect_does_not_release_in_flight_model_lease(tmp_path):
    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Original objective")
    contender = Reply("must never be called")

    class InFlight:
        def complete(self, *args, **kwargs):
            research.revise(db, "Redirect while inference is in flight", identifier)
            assert research.wake(db, tmp_path, contender, owner="contender") == "HELD"
            return ModelTurn("obsolete reply", output_tokens=1)

    assert research.wake(db, tmp_path, InFlight()) == "HELD"
    assert contender.calls == 0
    assert research.head(db, identifier)["calls"] == 1
    lease = db.connection.execute("SELECT * FROM research_profile").fetchone()
    assert lease["inference_owner"] == ""


def test_objective_snapshots_are_immutable_and_beliefs_remain_revisable(tmp_path):
    import sqlite3

    db = research.open_agent(tmp_path)
    identifier = research.revise(db, "Original question")
    research.revise(db, "Revised question", identifier)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with db.immediate() as connection:
            connection.execute("DELETE FROM research_revisions")
    assert [e["question"] for e in research.history(db, identifier)] == [
        "Original question",
        "Revised question",
    ]
