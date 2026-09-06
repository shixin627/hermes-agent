"""Durable local return addresses and results; account credentials never enter Hermes.

The native host drains this outbox with its current authenticated account. Rows
are acknowledged only after the cloud accepts their stable execution id.
"""
import json
import sqlite3
from contextlib import contextmanager

from hermes_constants import get_hermes_home


@contextmanager
def _db():
    directory = get_hermes_home() / "cron"
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "cloud-delivery.db", timeout=10)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS bindings (session TEXT PRIMARY KEY, body TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS results (id TEXT PRIMARY KEY, account TEXT NOT NULL, body TEXT NOT NULL)")
        with db:
            yield db
    finally:
        db.close()


def bind(session, binding):
    import re
    expected = {"accountUid", "conversationId", "instanceId"}
    if set(binding) != expected or not session or not all(isinstance(v, str) and v for v in binding.values()):
        raise ValueError("Invalid cloud conversation binding")
    for field, prefix in (("conversationId", "botconv"), ("instanceId", "botinst")):
        if not re.fullmatch(prefix + r"_[0-9a-f-]{36}", binding[field]):
            raise ValueError("Invalid cloud conversation address")
    with _db() as db:
        body = json.dumps(binding, sort_keys=True)
        old = db.execute("SELECT body FROM bindings WHERE session=?", (session,)).fetchone()
        if old and old[0] != body:
            raise ValueError("Cloud session cannot be rebound")
        db.execute("INSERT OR IGNORE INTO bindings VALUES (?,?)", (session, body))


def origin(session):
    if not session:
        return None
    with _db() as db:
        row = db.execute("SELECT body FROM bindings WHERE session=?", (session,)).fetchone()
    if not row:
        return None
    binding = json.loads(row[0])
    return {"platform": "skailink", "chat_id": binding["conversationId"], "cloud": binding}


def enqueue(job, content):
    binding = job["origin"]["cloud"]
    execution = job.get("execution_id")
    if not execution:
        raise ValueError("Cloud delivery requires a durable execution id")
    # Preserve complete output, including failed-run notices. Never truncate silently.
    body = {**binding, "idempotencyKey": str(execution),
            "content": f'排程「{job.get("name") or job["id"]}」\n\n{content}'}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True)
    with _db() as db:
        old = db.execute("SELECT body FROM results WHERE id=?", (str(execution),)).fetchone()
        if old and old[0] != encoded:
            raise ValueError("Conflicting output for the same scheduled execution")
        db.execute("INSERT OR IGNORE INTO results VALUES (?,?,?)", (str(execution), binding["accountUid"], encoded))


def pending(account):
    with _db() as db:
        return [json.loads(row[0]) for row in db.execute(
            "SELECT body FROM results WHERE account=? ORDER BY rowid", (account,))]


def acknowledge(account, execution):
    with _db() as db:
        db.execute("DELETE FROM results WHERE account=? AND id=?", (account, execution))
