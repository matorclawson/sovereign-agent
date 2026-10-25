"""Operator-granted campaigns outlive neither their clocks nor cumulative caps.

Investigations and evidence have no expiry. Campaigns admit work, and the call
ledger distinguishes actual output from reserved, released and unknown exposure.
All records live in the existing agent.sqlite; callers hold write transactions.
"""

from __future__ import annotations

import time
from typing import Any

from sovereign_agent.database import Database
from sovereign_agent.events import append_event

CAPS = {"calls": 12, "tokens": 12000, "actions": 24, "evaluations": 12}
LIMITS = {
    "calls": "call_limit",
    "tokens": "token_limit",
    "actions": "action_limit",
    "evaluations": "evaluation_limit",
}


def record(db: Database, identifier: str, kind: str, **payload: Any) -> None:
    append_event(db, "research." + kind, {"investigation": identifier, **payload})


def current(db: Database, identifier: str) -> dict[str, Any] | None:
    row = db.connection.execute(
        "SELECT * FROM research_campaigns WHERE investigation=? AND state='OPEN'",
        (identifier,),
    ).fetchone()
    return dict(row) if row else None


def require(db: Database, identifier: str, campaign: str = "") -> dict[str, Any]:
    row = current(db, identifier)
    if not row or row["deadline"] <= time.time() or (campaign and row["id"] != campaign):
        raise PermissionError("available authorized campaign required; use allow, then resume")
    return row


def grant(
    db: Database,
    identifier: str,
    key: str,
    seconds: int,
    source: str,
    limits: dict[str, int] | None = None,
) -> str:
    limits = CAPS if limits is None else limits
    if (
        not key
        or len(key) > 100
        or not source.strip()
        or len(source) > 512
        or type(seconds) is not int
        or not 1 <= seconds <= 600
        or set(limits) != set(CAPS)
        or any(
            type(v) is not int or not (0 if k == "evaluations" else 1) <= v <= CAPS[k]
            for k, v in limits.items()
        )
    ):
        raise ValueError("bounded campaign and explicit operator provenance required")
    existing = db.connection.execute(
        "SELECT * FROM research_campaigns WHERE id=?", (key,)
    ).fetchone()
    if existing:
        if existing["investigation"] != identifier or existing["source"] != source:
            raise ValueError("campaign identity already used")
        return key  # Never refresh a retry's expiry or counters.
    totals = db.connection.execute(
        "SELECT * FROM investigations WHERE id=?", (identifier,)
    ).fetchone()
    if totals is None:
        raise ValueError("unknown investigation")
    remaining = {k: min(limits[k], CAPS[k] - totals[k]) for k in CAPS}
    if min(remaining[k] for k in ("calls", "tokens", "actions")) <= 0:
        raise PermissionError("cumulative ceiling exhausted; campaign cannot reset it")
    db.connection.execute(
        "UPDATE research_campaigns SET state='CLOSED' WHERE investigation=? AND state='OPEN'",
        (identifier,),
    )
    db.connection.execute(
        "UPDATE assistant_work SET status='CANCELED',generation=generation+1 "
        "WHERE session=? AND role='investigation' AND status IN ('READY','RUNNING','BLOCKED')",
        (identifier,),
    )
    db.connection.execute(
        "INSERT INTO research_campaigns(id,investigation,deadline,source,call_limit,token_limit,"
        "action_limit,evaluation_limit) VALUES (?,?,?,?,?,?,?,?)",
        (
            key,
            identifier,
            time.time() + seconds,
            source,
            remaining["calls"],
            remaining["tokens"],
            remaining["actions"],
            remaining["evaluations"],
        ),
    )
    record(
        db,
        identifier,
        "allowance_granted",
        campaign=key,
        seconds=seconds,
        limits=remaining,
        source=source,
    )
    return key


def expire(db: Database) -> None:
    for row in db.connection.execute(
        "SELECT * FROM research_campaigns WHERE state='OPEN'"
    ).fetchall():
        reason = "campaign wall allowance expired" if row["deadline"] <= time.time() else ""
        if not reason and any(row[k] >= row[LIMITS[k]] for k in ("calls", "tokens", "actions")):
            reason = "campaign resource allowance exhausted"
        if reason:
            db.connection.execute(
                "UPDATE research_campaigns SET state='EXPIRED' WHERE id=?", (row["id"],)
            )
            db.connection.execute(
                "UPDATE investigations SET state=CASE WHEN state='ACTIVE' "
                "THEN 'WAITING_ALLOWANCE' ELSE state END,wake=? WHERE id=?",
                (reason, row["investigation"]),
            )
            record(db, row["investigation"], "allowance_expired", campaign=row["id"], reason=reason)
    lease = db.connection.execute("SELECT * FROM research_profile WHERE id=1").fetchone()
    if lease and lease["inference_owner"] and lease["inference_until"] <= time.time():
        row = db.connection.execute(
            "SELECT w.investigation FROM research_inference r "
            "JOIN research_work w ON w.work_id=r.work_id WHERE r.id=?",
            (lease["inference_owner"],),
        ).fetchone()
        db.connection.execute(
            "UPDATE research_profile SET inference_owner='',inference_until=0 WHERE id=1"
        )
        if row:
            record(
                db,
                row[0],
                "stale_inference_retired",
                reservation=lease["inference_owner"],
                usage="UNKNOWN; exposure retained",
            )


def charge(db: Database, identifier: str, campaign: str, resource: str, amount: int) -> None:
    row = require(db, identifier, campaign)
    total = db.connection.execute(
        f"SELECT {resource} FROM investigations WHERE id=?", (identifier,)
    ).fetchone()[0]
    if (
        amount < 0
        or row[resource] + amount > row[LIMITS[resource]]
        or total + amount > CAPS[resource]
    ):
        raise PermissionError("campaign or cumulative " + resource + " ceiling exhausted")
    db.connection.execute(
        f"UPDATE investigations SET {resource}={resource}+? WHERE id=?", (amount, identifier)
    )
    db.connection.execute(
        f"UPDATE research_campaigns SET {resource}={resource}+? WHERE id=?", (amount, campaign)
    )


def settle(db: Database, reservation: str, consumed: int | None, detail: str) -> None:
    row = db.connection.execute(
        "SELECT r.*,w.investigation FROM research_inference r "
        "JOIN research_work w ON w.work_id=r.work_id WHERE r.id=?",
        (reservation,),
    ).fetchone()
    if row is None or row["status"] not in {"RESERVED", "UNKNOWN"}:
        raise ValueError("reservation missing or already reconciled")
    if consumed is not None and not 0 <= consumed <= row["reserved"]:
        raise ValueError("usage exceeds reserved allowance")
    released = 0 if consumed is None else row["reserved"] - consumed
    state = "UNKNOWN" if consumed is None else "RELEASED" if consumed == 0 else "CONSUMED"
    db.connection.execute(
        "UPDATE research_inference SET status=?,consumed=?,detail=? WHERE id=?",
        (state, consumed or 0, detail, reservation),
    )
    db.connection.execute(
        "UPDATE investigations SET tokens=tokens-? WHERE id=?", (released, row["investigation"])
    )
    db.connection.execute(
        "UPDATE research_campaigns SET tokens=tokens-? WHERE id=?", (released, row["campaign"])
    )
    record(
        db,
        row["investigation"],
        "usage_reconciled",
        reservation=reservation,
        status=state,
        consumed=consumed,
        released=released,
        detail=detail,
    )


def status(db: Database, identifier: str) -> dict[str, Any]:
    campaigns = [
        dict(r)
        for r in db.connection.execute(
            "SELECT * FROM research_campaigns WHERE investigation=? ORDER BY rowid", (identifier,)
        )
    ]
    usage = [
        dict(r)
        for r in db.connection.execute(
            "SELECT r.* FROM research_inference r JOIN research_work w "
            "ON w.work_id=r.work_id WHERE w.investigation=?",
            (identifier,),
        )
    ]
    return {
        "campaigns": campaigns,
        "inference": usage,
        "reserved": sum(r["reserved"] for r in usage if r["status"] == "RESERVED"),
        "unknown": sum(r["reserved"] for r in usage if r["status"] == "UNKNOWN"),
        "consumed": sum(r["consumed"] for r in usage),
        "released": sum(
            r["reserved"] - r["consumed"] for r in usage if r["status"] in {"RELEASED", "CONSUMED"}
        ),
    }
