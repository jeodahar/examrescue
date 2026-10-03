"""database.py - tiny SQLite memory for ExamRescue AI.

NOTE: On Streamlit Cloud the file system is temporary. The data can reset when
the app sleeps or redeploys. Use the Backup / Restore buttons in the sidebar.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

import pandas as pd

DB_PATH = "examrescue.db"
TABLES = ["profile", "topics", "study_log", "assessments", "plans"]


@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                exam TEXT, exam_date TEXT, start_date TEXT, daily_hours REAL);
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT, topic TEXT,
                importance INTEGER DEFAULT 3,
                hours_needed REAL DEFAULT 2,
                hours_done REAL DEFAULT 0,
                score REAL,
                past_freq INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS study_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT, hours REAL, missed INTEGER DEFAULT 0, topic_id INTEGER);
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER, day TEXT, score REAL,
                mistake_type TEXT, feedback TEXT);
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created TEXT, summary TEXT, plan_json TEXT,
                narrative TEXT, changes TEXT);
            """
        )


# ---------- profile ----------
def get_profile():
    with _conn() as c:
        row = c.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        return dict(row) if row else None


def save_profile(exam, exam_date, daily_hours):
    old = get_profile()
    start = old["start_date"] if old else date.today().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO profile VALUES (1, ?, ?, ?, ?)",
            (exam, exam_date.isoformat(), start, float(daily_hours)),
        )


# ---------- topics ----------
def add_topics(rows):
    """rows: list of dicts with subject, topic, importance, hours. Skips duplicates."""
    added = 0
    with _conn() as c:
        for r in rows:
            subject = str(r.get("subject", "General")).strip()[:80]
            topic = str(r.get("topic", "")).strip()[:120]
            if not topic:
                continue
            exists = c.execute(
                "SELECT 1 FROM topics WHERE lower(subject)=lower(?) AND lower(topic)=lower(?)",
                (subject, topic),
            ).fetchone()
            if exists:
                continue
            try:
                imp = max(1, min(5, int(r.get("importance", 3))))
            except Exception:
                imp = 3
            try:
                hrs = max(0.5, min(40.0, float(r.get("hours", 2))))
            except Exception:
                hrs = 2.0
            c.execute(
                "INSERT INTO topics (subject, topic, importance, hours_needed) VALUES (?,?,?,?)",
                (subject, topic, imp, hrs),
            )
            added += 1
    return added


def topics_df():
    with _conn() as c:
        return pd.read_sql_query("SELECT * FROM topics ORDER BY subject, id", c)


def update_topics(df):
    with _conn() as c:
        for r in df.itertuples():
            score = None if pd.isna(r.score) else float(r.score)
            c.execute(
                "UPDATE topics SET importance=?, hours_needed=?, hours_done=?, score=?, past_freq=? WHERE id=?",
                (
                    int(r.importance), float(r.hours_needed), float(r.hours_done),
                    score, int(r.past_freq), int(r.id),
                ),
            )


def clear_topics():
    with _conn() as c:
        c.execute("DELETE FROM topics")
        c.execute("DELETE FROM assessments")


def set_past_freq(mapping):
    """mapping: {topic name: frequency 0-5}. Adds to the existing value (max 5)."""
    low = {str(k).strip().lower(): v for k, v in mapping.items()}
    changed = 0
    with _conn() as c:
        for row in c.execute("SELECT id, topic, past_freq FROM topics").fetchall():
            val = low.get(row["topic"].strip().lower())
            if val is None:
                continue
            try:
                val = int(val)
            except Exception:
                continue
            new = max(0, min(5, (row["past_freq"] or 0) + val))
            c.execute("UPDATE topics SET past_freq=? WHERE id=?", (new, row["id"]))
            changed += 1
    return changed


# ---------- study log ----------
def add_log(hours, missed=0, topic_id=None, day=None):
    day = day or date.today().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO study_log (day, hours, missed, topic_id) VALUES (?,?,?,?)",
            (day, float(hours), int(missed), topic_id),
        )
        if topic_id and hours > 0:
            c.execute(
                "UPDATE topics SET hours_done = hours_done + ? WHERE id = ?",
                (float(hours), int(topic_id)),
            )


def get_logs():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM study_log").fetchall()]


# ---------- assessments ----------
def add_assessment(topic_id, score, mistake_type, feedback):
    with _conn() as c:
        c.execute(
            "INSERT INTO assessments (topic_id, day, score, mistake_type, feedback) VALUES (?,?,?,?,?)",
            (int(topic_id), date.today().isoformat(), float(score), mistake_type, feedback),
        )
        prior = c.execute("SELECT score FROM topics WHERE id=?", (int(topic_id),)).fetchone()
        if prior and prior["score"] is not None:
            new = round(0.4 * prior["score"] + 0.6 * float(score), 1)  # recent result counts more
        else:
            new = float(score)
        c.execute("UPDATE topics SET score=? WHERE id=?", (new, int(topic_id)))


def assessments_df():
    with _conn() as c:
        return pd.read_sql_query(
            """SELECT a.id, a.topic_id, t.subject, t.topic, a.day, a.score, a.mistake_type
               FROM assessments a JOIN topics t ON t.id = a.topic_id ORDER BY a.id""",
            c,
        )


# ---------- saved recovery plans (auto re-plan history) ----------
def save_plan(summary, plan_df, narrative, changes):
    with _conn() as c:
        c.execute(
            "INSERT INTO plans (created, summary, plan_json, narrative, changes) VALUES (?,?,?,?,?)",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                json.dumps(summary),
                plan_df[["topic", "category", "hours"]].to_json(orient="records"),
                narrative or "",
                json.dumps(changes),
            ),
        )


def latest_plan():
    with _conn() as c:
        row = c.execute("SELECT * FROM plans ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


# ---------- backup / restore ----------
def export_json():
    out = {}
    with _conn() as c:
        for t in TABLES:
            out[t] = [dict(r) for r in c.execute(f"SELECT * FROM {t}").fetchall()]
    return json.dumps(out, indent=2)


def import_json(text):
    data = json.loads(text)
    with _conn() as c:
        for t in TABLES:
            cols = [r["name"] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
            c.execute(f"DELETE FROM {t}")
            for row in data.get(t, []):
                keys = [k for k in row if k in cols]
                if not keys:
                    continue
                q = f"INSERT INTO {t} ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})"
                c.execute(q, [row[k] for k in keys])
