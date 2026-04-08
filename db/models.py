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

CREATE INDEX IF NOT EXISTS idx_group_members_group ON group_members(group_id);
CREATE INDEX IF NOT EXISTS idx_group_members_user ON group_members(telegram_id);
CREATE INDEX IF NOT EXISTS idx_loans_group_pair ON loans(group_id, lender_id, borrower_id, status);
CREATE INDEX IF NOT EXISTS idx_loans_group_created ON loans(group_id, created_at);
CREATE INDEX IF NOT EXISTS idx_payments_loan ON payments(loan_id);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(db_path)) as db:
        db.executescript(SCHEMA)
        db.commit()
