"""Transactional run state and ordered events. SQLite locally; PostgreSQL on a server."""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Callable

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
    update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    repo: Mapped[str] = mapped_column(String(200))
    issue: Mapped[int] = mapped_column(Integer)
    created: Mapped[float] = mapped_column(Float)
    updated: Mapped[float] = mapped_column(Float)
    version: Mapped[int] = mapped_column(Integer, default=0)
    cancel: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_owner: Mapped[str] = mapped_column(String(60), default="")
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    data: Mapped[dict] = mapped_column(JSON)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    created: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)


class Delivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("delivery_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(String(200))
    created: Mapped[float] = mapped_column(Float)


TERMINAL = {
    "awaiting_approval",
    "pr_opened",
    "demo_complete",
    "failed",
    "needs_input",
    "cancelled",
    "rejected",
    "stale",
}


class Conflict(Exception):
    pass


class Store:
    def __init__(self, url: str):
        kwargs = (
            {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {}
        )
        self.engine = create_engine(url, **kwargs)
        Base.metadata.create_all(self.engine)

    @staticmethod
    def serialize(row: Run) -> dict:
        return dict(
            id=row.id,
            status=row.status,
            repo=row.repo,
            issue=row.issue,
            created=row.created,
            updated=row.updated,
            cancel=row.cancel,
            **copy.deepcopy(row.data),
        )

    def has_active_runs(self):
        with Session(self.engine) as s:
            return s.scalar(select(Run.id).where(Run.status.not_in(TERMINAL)).limit(1)) is not None

    def create(self, repo: str, issue: int, data: dict, key: str, *, status="queued") -> dict:
        # Model switches use the same durable run inventory, including older queued jobs.
        # Idempotency key belongs to this single-owner installation.
        run_id = uuid.uuid5(uuid.NAMESPACE_URL, "forge:" + key).hex
        with Session(self.engine) as s, s.begin():
            existing = s.get(Run, run_id)
            if existing:
                if (
                    existing.repo != repo
                    or existing.issue != issue
                    or existing.data["mode"] != data["mode"]
                    or existing.data.get("request", "") != data.get("request", "")
                    or bool(existing.data.get("conversation_only")) != bool(data.get("conversation_only"))
                ):
                    raise Conflict("This request key was already used for a different run.")
                return self.serialize(existing)
            now = time.time()
            row = Run(id=run_id, repo=repo, issue=issue, status=status, created=now, updated=now, data=data)
            s.add(row)
            s.flush()
            s.add(
                Event(
                    run_id=run_id,
                    created=now,
                    kind=status,
                    message="Conversation opened. No execution started."
                    if status == "needs_input"
                    else "Run queued. No repository writes authorized.",
                )
            )
            return self.serialize(row)

    def get(self, run_id: str) -> dict:
        with Session(self.engine) as s:
            row = s.get(Run, run_id)
            if not row:
                raise KeyError(run_id)
            return self.serialize(row)

    def list(self, repo: str | None = None, before: float | None = None) -> list[dict]:
        with Session(self.engine) as s:
            q = select(Run).order_by(Run.created.desc()).limit(50)
            if repo:
                q = q.where(Run.repo == repo)
            if before is not None:
                q = q.where(Run.created < before)
            return [self.serialize(r) for r in s.scalars(q)]

    def session_action(self, run_id, action):
        if action == "delete":
            with Session(self.engine) as s, s.begin():
                row = s.get(Run, run_id)
                if row is None:
                    raise KeyError(run_id)
                if row.status not in TERMINAL or row.lease_until > time.time():
                    raise Conflict("End this session and wait for execution to stop before deleting it.")
                if any(t.get("status") == "pending" for t in row.data.get("chat", [])):
                    raise Conflict("Wait for the current reply before deleting this session.")
                for event in s.scalars(select(Event).where(Event.run_id == run_id)):
                    s.delete(event)
                s.delete(row)
            return {"deleted": True, "id": run_id}

        def change(row, data):
            if row.status == "publishing":
                raise Conflict("Publication is in progress. Wait for it to finish.")
            if action == "end":
                data["ended"] = True
                return {"cancel": True, "status": "cancelled"}
            if any(t.get("status") == "pending" for t in data.get("chat", [])):
                raise Conflict("Wait for the current reply before forgetting conversation context.")
            data["chat"] = []
            data["forgotten_at"] = time.time()

        return self.mutate(
            run_id,
            change,
            "session_" + action,
            "Session ended; published GitHub history is unchanged."
            if action == "end"
            else "Conversation context forgotten. Run and PR records are preserved.",
        )

    def mutate(self, run_id: str, fn: Callable, kind: str = "", message: str = "", owner: str = "") -> dict:
        for _ in range(8):
            with Session(self.engine) as s, s.begin():
                row = s.get(Run, run_id)
                if row is None:
                    raise KeyError(run_id)
                if owner and (row.lease_owner != owner or row.lease_until < time.time()):
                    raise Conflict("Worker lease expired.")
                data = copy.deepcopy(row.data)
                fields = fn(row, data) or {}
                fields.update(data=data, updated=time.time(), version=row.version + 1)
                result = s.execute(
                    update(Run).where(Run.id == run_id, Run.version == row.version).values(**fields)
                )
                if result.rowcount:
                    if kind:
                        s.add(Event(run_id=run_id, created=time.time(), kind=kind, message=message[:4000]))
                    s.expire(row)
                    return self.serialize(row)
        raise Conflict("Run changed concurrently. Refresh and retry.")

    def claim(self, owner: str) -> dict | None:
        # A conditional UPDATE prevents duplicate claims without relying on SQLite row locks.
        with Session(self.engine) as s, s.begin():
            if s.scalar(select(Run.id).where(Run.lease_until > time.time()).limit(1)):
                return None
            row = s.scalar(
                select(Run)
                .where(Run.status.in_(["queued", "publishing"]), Run.lease_until < time.time())
                .order_by(Run.created)
                .limit(1)
            )
            if not row:
                return None
            result = s.execute(
                update(Run)
                .where(Run.id == row.id, Run.version == row.version, Run.lease_until < time.time())
                .values(lease_owner=owner, lease_until=time.time() + 60, version=row.version + 1)
            )
            if not result.rowcount:
                return None
            s.expire(row)
            return self.serialize(row)

    def heartbeat(self, run_id: str, owner: str) -> None:
        with Session(self.engine) as s, s.begin():
            s.execute(
                update(Run)
                .where(Run.id == run_id, Run.lease_owner == owner, Run.lease_until > time.time())
                .values(lease_until=time.time() + 60)
            )

    def recover(self) -> None:
        with Session(self.engine) as s, s.begin():
            rows = list(
                s.scalars(
                    select(Run).where(
                        Run.status.notin_(TERMINAL | {"queued", "publishing"}), Run.lease_until < time.time()
                    )
                )
            )
            for row in rows:
                row.status = "failed"
                row.data = {
                    **row.data,
                    "error": "Worker interrupted. Start a new run to revalidate from the base.",
                }
                row.version += 1
                s.add(
                    Event(
                        run_id=row.id,
                        created=time.time(),
                        kind="failed",
                        message="Worker interrupted; no approval or patch was silently reused.",
                    )
                )

    def events(self, run_id: str, after: int = 0) -> list[dict]:
        with Session(self.engine) as s:
            return [
                dict(id=e.id, kind=e.kind, message=e.message, created=e.created)
                for e in s.scalars(
                    select(Event)
                    .where(Event.run_id == run_id, Event.id > after)
                    .order_by(Event.id)
                    .limit(300)
                )
            ]

    def revise(self, run_id: str, feedback: str, key: str) -> dict:
        new_id = uuid.uuid5(uuid.NAMESPACE_URL, "forge:" + key).hex
        with Session(self.engine) as s, s.begin():
            previous = s.get(Run, run_id)
            if previous is None:
                raise KeyError(run_id)
            existing = s.get(Run, new_id)
            if existing:
                if existing.data.get("parent_run") != run_id or existing.data.get("feedback") != feedback:
                    raise Conflict("Request key belongs to another revision.")
                return self.serialize(existing)
            if previous.status not in {
                "awaiting_approval",
                "pr_opened",
                "rejected",
                "failed",
                "cancelled",
                "stale",
                "needs_input",
            }:
                raise Conflict("Wait for this run to finish before requesting changes.")
            if previous.data["mode"] == "demo":
                raise Conflict("The bundled demo has a fixed proposal. Revisions require a real model run.")
            old_data = copy.deepcopy(previous.data)
            old_data["revision_run"] = new_id
            changed = s.execute(
                update(Run)
                .where(Run.id == run_id, Run.version == previous.version)
                .values(
                    status="rejected" if previous.status == "awaiting_approval" else previous.status,
                    data=old_data,
                    updated=time.time(),
                    version=previous.version + 1,
                )
            )
            if not changed.rowcount:
                raise Conflict("Proposal changed during revision. Refresh before continuing.")
            now = time.time()
            row = Run(
                id=new_id,
                repo=previous.repo,
                issue=previous.issue,
                status="queued",
                created=now,
                updated=now,
                data={
                    "mode": "github",
                    "title": feedback.splitlines()[0][:200]
                    if previous.data.get("conversation_only")
                    else previous.data["title"],
                    "parent_run": run_id,
                    "feedback": feedback,
                    "request": feedback
                    if previous.data.get("conversation_only")
                    else previous.data.get("request", ""),
                    "previous_request": previous.data.get("feedback", ""),
                    "previous_publication": previous.data.get("publication"),
                    "requested_profile": previous.data.get("requested_profile", "auto"),
                    "usage": {"calls": 0, "tokens": 0, "cost": 0},
                    "checks": [],
                    "repairs": 0,
                },
            )
            s.add(row)
            s.flush()
            s.add(
                Event(
                    run_id=run_id,
                    created=now,
                    kind="revision_requested",
                    message="Owner requested a follow-up proposal. Published history is preserved; any pending candidate is retired.",
                )
            )
            s.add(
                Event(
                    run_id=new_id,
                    created=now,
                    kind="queued",
                    message="New run requested with owner feedback. The base and checks will be refreshed.",
                )
            )
            return self.serialize(row)

    def delivery(self, delivery_id: str) -> bool:
        from sqlalchemy.exc import IntegrityError

        try:
            with Session(self.engine) as s, s.begin():
                s.add(Delivery(delivery_id=delivery_id, created=time.time()))
            return True
        except IntegrityError:
            return False
