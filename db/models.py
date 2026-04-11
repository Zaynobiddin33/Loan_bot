from __future__ import annotations

from pathlib import Path
import sqlite3


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    admin_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS group_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER REFERENCES groups(id),
    telegram_id BIGINT NOT NULL,
    username TEXT,
    full_name TEXT,
    card_number TEXT,
    trash_order_position INTEGER,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(group_id, telegram_id)
);

CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER REFERENCES groups(id),
    lender_id BIGINT NOT NULL,
    borrower_id BIGINT NOT NULL,
    amount REAL NOT NULL,
    comment TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id INTEGER REFERENCES loans(id),
    payer_id BIGINT NOT NULL,
    amount REAL NOT NULL,
    proof_type TEXT,
    proof_content TEXT,
    note TEXT,
    approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trash_rotation_settings (
    group_id INTEGER PRIMARY KEY REFERENCES groups(id) ON DELETE CASCADE,
    start_date TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_group_members_group ON group_members(group_id);
CREATE INDEX IF NOT EXISTS idx_group_members_user ON group_members(telegram_id);
CREATE INDEX IF NOT EXISTS idx_group_members_trash_order ON group_members(group_id, trash_order_position);
CREATE INDEX IF NOT EXISTS idx_loans_group_pair ON loans(group_id, lender_id, borrower_id, status);
CREATE INDEX IF NOT EXISTS idx_loans_group_created ON loans(group_id, created_at);
CREATE INDEX IF NOT EXISTS idx_payments_loan ON payments(loan_id);
"""


def _ensure_group_members_trash_order_column(db: sqlite3.Connection) -> None:
    columns = {row[1] for row in db.execute("PRAGMA table_info(group_members)")}
    if "trash_order_position" not in columns:
        db.execute("ALTER TABLE group_members ADD COLUMN trash_order_position INTEGER")

    group_rows = db.execute("SELECT id FROM groups ORDER BY id").fetchall()
    for group_row in group_rows:
        group_id = group_row[0]
        member_rows = db.execute(
            """
            SELECT id
            FROM group_members
            WHERE group_id = ?
            ORDER BY
                CASE WHEN trash_order_position IS NULL THEN 1 ELSE 0 END,
                trash_order_position,
                joined_at,
                id
            """,
            (group_id,),
        ).fetchall()
        for index, member_row in enumerate(member_rows, start=1):
            db.execute(
                "UPDATE group_members SET trash_order_position = ? WHERE id = ?",
                (index, member_row[0]),
            )


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(db_path)) as db:
        db.executescript(SCHEMA)
        _ensure_group_members_trash_order_column(db)
        db.commit()
