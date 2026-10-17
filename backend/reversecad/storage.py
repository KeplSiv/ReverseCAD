"""Small durable SQLite store; every job input is an immutable snapshot."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ACTIVE_STATES = {"queued", "validating_input", "reconstructing", "planning", "generating_cad", "validating_cad"}
TERMINAL_STATES = {"complete", "failed", "cancelled", "needs_input"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + str(threading.get_ident()))
    with temp.open("w") as stream:
        json.dump(value, stream, allow_nan=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.database = root / "state.sqlite3"
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS scans (
                    scan_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner TEXT NOT NULL,
                    source TEXT NOT NULL, committed INTEGER NOT NULL DEFAULT 0,
                    annotation_revision INTEGER NOT NULL DEFAULT 0, reconstruction TEXT,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    owner TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
                    request TEXT NOT NULL, result TEXT, error TEXT,
                    repair_id TEXT, revision INTEGER, request_id TEXT, request_hash TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(owner, request_id)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, owner TEXT NOT NULL,
                    path TEXT NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_revision ON jobs(repair_id,revision);
            """)

    @contextmanager
    def connect(self):
        with self.lock:
            db = sqlite3.connect(self.database, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def one(self, sql, args=()):
        with self.connect() as db:
            row = db.execute(sql, args).fetchone()
            return dict(row) if row else None

    def all(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]

    def update_job(self, job_id, state, progress=0, message="", result=None, error=None):
        with self.connect() as db:
            row = db.execute("SELECT state FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None or row["state"] == "cancelled":
                return
            db.execute("UPDATE jobs SET state=?,progress=?,message=?,result=?,error=?,updated_at=? WHERE job_id=? AND state<>'cancelled'", (state,progress,message,json.dumps(result) if result is not None else None,json.dumps(error) if error is not None else None,time.time(),job_id))

    def recover(self):
        with self.connect() as db:
            active = tuple(ACTIVE_STATES - {"queued"})
            marks = ",".join("?" for _ in active)
            db.execute(f"UPDATE jobs SET state='failed',error=?,message=?,updated_at=? WHERE state IN ({marks})", (json.dumps({"code":"server_restarted","message":"Service stopped during processing; scan is preserved. Retry creates a new job."}),"Interrupted by service restart",time.time(),*active))

    def scan_dir(self, scan_id):
        return self.root / "scans" / scan_id / "capture"

    def annotations(self, scan):
        revision = scan["annotation_revision"]
        file = self.root / "scans" / scan["scan_id"] / "annotations" / f"{revision}.json"
        if revision and file.is_file():
            return json.loads(file.read_text())
        original = self.scan_dir(scan["scan_id"]) / "annotations.json"
        return json.loads(original.read_text()) if original.is_file() else {}
