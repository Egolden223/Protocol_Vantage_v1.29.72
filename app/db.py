"""db.py -- Persistance SQLite (walk-forward : historique des courses traitées,
consultable pour un audit post-course, cf. RAPPEL FINAL des instructions)."""
from __future__ import annotations
import sqlite3
import json
import os
import threading
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from app import config

_lock = threading.Lock()
logger = logging.getLogger("vantage.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DATABASE_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS races (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                hippodrome TEXT,
                reunion_course_label TEXT,
                error TEXT,
                stage_collecte TEXT,
                result TEXT,
                audit TEXT
            )
        """)
        try:
            conn.execute("ALTER TABLE races ADD COLUMN audit TEXT")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente (base existante)
        try:
            conn.execute("ALTER TABLE races ADD COLUMN execution_report TEXT")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente (base existante)
        conn.commit()


def create_race(race_id: str, urls) -> None:
    now = datetime.now(timezone.utc).isoformat()
    url_field = json.dumps(urls, ensure_ascii=False) if isinstance(urls, list) else urls
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO races (id, url, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (race_id, url_field, "EN_ATTENTE", now, now),
        )
        conn.commit()


def update_status(race_id: str, status: str, error: Optional[str] = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        if error is not None:
            conn.execute("UPDATE races SET status=?, error=?, updated_at=? WHERE id=?",
                         (status, error, now, race_id))
        else:
            conn.execute("UPDATE races SET status=?, updated_at=? WHERE id=?", (status, now, race_id))
        conn.commit()
    if status in ("TERMINE", "ERREUR", "REJETEE_CHAMP_TROP_PETIT"):
        hf_schedule(race_id)


def save_stage_collecte(race_id: str, data: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    hippo = data.get("race", {}).get("hippodrome")
    label = data.get("race", {}).get("reunion_course_label")
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE races SET stage_collecte=?, hippodrome=?, reunion_course_label=?, updated_at=? WHERE id=?",
            (json.dumps(data, ensure_ascii=False), hippo, label, now, race_id),
        )
        conn.commit()


def save_result(race_id: str, result_dict: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        conn.execute("UPDATE races SET result=?, updated_at=? WHERE id=?",
                     (json.dumps(result_dict, ensure_ascii=False, default=str), now, race_id))
        conn.commit()


def parse_urls(url_field: str) -> List[str]:
    try:
        parsed = json.loads(url_field)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return [url_field]


def save_audit(race_id: str, audit_dict: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        conn.execute("UPDATE races SET audit=?, updated_at=? WHERE id=?",
                     (json.dumps(audit_dict, ensure_ascii=False, default=str), now, race_id))
        conn.commit()
    hf_schedule(race_id)           # l'audit post-course part aussi vers Hugging Face


def save_execution_report(race_id: str, report_dict: Dict[str, Any]) -> None:
    """Appelée en incrémental après CHAQUE étape du pipeline (pas
    seulement à la fin) -- pour que le rapport soit consultable même si
    le pipeline plante avant la fin (c'est justement le cas qu'on veut
    pouvoir diagnostiquer)."""
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as conn:
        conn.execute("UPDATE races SET execution_report=?, updated_at=? WHERE id=?",
                     (json.dumps(report_dict, ensure_ascii=False, default=str), now, race_id))
        conn.commit()


def get_race(race_id: str) -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM races WHERE id=?", (race_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["urls"] = parse_urls(d["url"])
        if d.get("stage_collecte"):
            d["stage_collecte"] = json.loads(d["stage_collecte"])
        if d.get("result"):
            d["result"] = json.loads(d["result"])
        if d.get("audit"):
            d["audit"] = json.loads(d["audit"])
        if d.get("execution_report"):
            d["execution_report"] = json.loads(d["execution_report"])
        return d


def list_races(limit: int = 50) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id, url, status, created_at, updated_at, hippodrome, reunion_course_label, error "
            "FROM races ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_audits(limit: int = 100) -> List[Dict[str, Any]]:
    """Audits des courses les plus récentes qui EN ONT un -- utilisé pour
    l'agrégation de patterns récurrents (cf. post_race_audit.py::
    aggregate_audit_patterns), ajouté le 06/09/2026."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id, hippodrome, reunion_course_label, created_at, audit FROM races "
            "WHERE audit IS NOT NULL ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["audit"] = json.loads(d["audit"])
            out.append(d)
        return out


def hf_schedule(race_id: str) -> None:
    """Déclenche la sauvegarde Hugging Face de cette course (non bloquant, ne lève jamais)."""
    try:
        from app.integrations.hf_export import schedule
        schedule(race_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("hf_schedule: %s", e)


def insert_row(row: Dict[str, Any]) -> None:
    """Réinsère une course complète (restauration depuis Hugging Face)."""
    def dumps(v):
        return json.dumps(v, ensure_ascii=False, default=str) if v is not None else None
    url_field = json.dumps(row.get("urls"), ensure_ascii=False) if isinstance(row.get("urls"), list) else row.get("url", "[]")
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO races (id, url, status, created_at, updated_at, hippodrome, reunion_course_label, error, "
            "stage_collecte, result, audit, execution_report) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], url_field, row.get("status") or "TERMINE", row.get("created_at"), row.get("updated_at"),
             row.get("hippodrome"), row.get("reunion_course_label"), row.get("error"),
             dumps(row.get("stage_collecte")), dumps(row.get("result")), dumps(row.get("audit")),
             dumps(row.get("execution_report"))))
        conn.commit()
