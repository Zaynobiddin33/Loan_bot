from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from config import DB_PATH
from utils.formatters import now_local

_DB_EXECUTOR = ThreadPoolExecutor(max_workers=2)


def _clean_name(full_name: str | None, username: str | None, telegram_id: int) -> str:
    if full_name and full_name.strip():
        return full_name.strip()
    if username and username.strip():
        return f"@{username.strip()}"
    return f"Noma'lum foydalanuvchi (#{telegram_id})"


def _member_name(member: dict[str, Any]) -> str:
    return _clean_name(member.get("full_name"), member.get("username"), member["telegram_id"])


def _normalize_trash_order_sync(db: sqlite3.Connection, group_id: int) -> None:
    cursor = db.execute(
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
    )
    member_rows = cursor.fetchall()
    for index, row in enumerate(member_rows, start=1):
        db.execute(
            "UPDATE group_members SET trash_order_position = ? WHERE id = ?",
            (index, row["id"]),
        )


def _next_trash_order_position_sync(db: sqlite3.Connection, group_id: int) -> int:
    cursor = db.execute(
        "SELECT COALESCE(MAX(trash_order_position), 0) AS max_position FROM group_members WHERE group_id = ?",
        (group_id,),
    )
    row = cursor.fetchone()
    return int(row["max_position"] or 0) + 1


def _date_text(value: date) -> str:
    return value.isoformat()


def _parse_date_text(value: str) -> date:
    return date.fromisoformat(value)


def _compute_trash_turn(
    members: Sequence[dict[str, Any]],
    start_date: date,
    target_date: date,
) -> dict[str, Any]:
    if not members:
        return {
            "is_skip_day": True,
            "assignee": None,
            "next_assignee": None,
            "next_turn_date": None,
        }

    if target_date < start_date:
        return {
            "is_skip_day": True,
            "assignee": None,
            "next_assignee": members[0],
            "next_turn_date": start_date,
        }

    day_offset = (target_date - start_date).days
    if day_offset % 2 == 1:
        next_cycle_index = (day_offset + 1) // 2
        return {
            "is_skip_day": True,
            "assignee": None,
            "next_assignee": members[next_cycle_index % len(members)],
            "next_turn_date": target_date + timedelta(days=1),
        }

    cycle_index = day_offset // 2
    return {
        "is_skip_day": False,
        "assignee": members[cycle_index % len(members)],
        "next_assignee": members[(cycle_index + 1) % len(members)],
        "next_turn_date": target_date + timedelta(days=2),
    }


def _run_sync_db(func):
    def _sync():
        with sqlite3.connect(str(DB_PATH)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON;")
            return func(db)

    loop = asyncio.get_running_loop()
    return loop.run_in_executor(_DB_EXECUTOR, _sync)


def _round_amount(value: float | int | Decimal) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def split_amount(total_amount: float | Decimal | str, parts: int) -> list[float]:
    if parts <= 0:
        raise ValueError("parts must be greater than zero")

    total = Decimal(str(total_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    base = (total / Decimal(parts)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    shares = [base for _ in range(parts)]
    remainder = total - (base * parts)
    shares[0] += remainder
    return [_round_amount(share) for share in shares]


def build_loan_distribution(
    total_amount: float | Decimal | str,
    participant_ids: Sequence[int],
    lender_id: int,
) -> dict[str, Any]:
    if not participant_ids:
        raise ValueError("participant_ids must not be empty")

    shares = split_amount(total_amount, len(participant_ids))
    participant_shares: list[dict[str, Any]] = []
    borrower_allocations: list[dict[str, Any]] = []
    lender_share = 0.0

    for participant_id, share in zip(participant_ids, shares, strict=True):
        participant_shares.append({"participant_id": participant_id, "amount": share})
        if participant_id == lender_id:
            lender_share = share
            continue

        borrower_allocations.append({"borrower_id": participant_id, "amount": share})

    return {
        "participant_shares": participant_shares,
        "borrower_allocations": borrower_allocations,
        "lender_share": lender_share,
        "borrower_total": _round_amount(sum(item["amount"] for item in borrower_allocations)),
    }


def sync_admins(admin_ids: Sequence[int]) -> None:
    if not admin_ids:
        return

    with sqlite3.connect(str(DB_PATH)) as db:
        db.executemany(
            "INSERT OR IGNORE INTO admins(telegram_id) VALUES (?)",
            [(admin_id,) for admin_id in admin_ids],
        )
        db.commit()


def sync_trash_rotations(start_date: date | None = None) -> None:
    start_date_text = _date_text(start_date or now_local().date())

    with sqlite3.connect(str(DB_PATH)) as db:
        db.execute(
            """
            INSERT INTO trash_rotation_settings(group_id, start_date)
            SELECT g.id, ?
            FROM groups g
            LEFT JOIN trash_rotation_settings trs ON trs.group_id = g.id
            WHERE trs.group_id IS NULL
            """,
            (start_date_text,),
        )
        db.commit()


async def is_admin(telegram_id: int) -> bool:
    def _sync(db):
        cursor = db.execute(
            "SELECT 1 FROM admins WHERE telegram_id = ? LIMIT 1",
            (telegram_id,),
        )
        row = cursor.fetchone()
        return row is not None

    return await _run_sync_db(_sync)


async def get_group(group_id: int) -> dict[str, Any] | None:
    def _sync(db):
        cursor = db.execute(
            """
            SELECT
                g.*,
                COUNT(gm.id) AS member_count
            FROM groups g
            LEFT JOIN group_members gm ON gm.group_id = g.id
            WHERE g.id = ?
            GROUP BY g.id
            """,
            (group_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    return await _run_sync_db(_sync)


async def get_group_name(group_id: int) -> str:
    group = await get_group(group_id)
    return group["name"] if group else "Noma'lum guruh"


async def create_group(
    name: str,
    admin_id: int,
    admin_username: str | None,
    admin_full_name: str,
) -> dict[str, Any]:
    start_date_text = _date_text(now_local().date())

    def _sync(db):
        cursor = db.execute(
            "INSERT INTO groups(name, admin_id) VALUES (?, ?)",
            (name, admin_id),
        )
        group_id = cursor.lastrowid

        db.execute(
            """
            INSERT INTO group_members(group_id, telegram_id, username, full_name, trash_order_position)
            VALUES (?, ?, ?, ?, ?)
            """,
            (group_id, admin_id, admin_username, admin_full_name, 1),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO trash_rotation_settings(group_id, start_date)
            VALUES (?, ?)
            """,
            (group_id, start_date_text),
        )
        db.commit()

        cursor = db.execute(
            """
            SELECT
                g.*,
                COUNT(gm.id) AS member_count
            FROM groups g
            LEFT JOIN group_members gm ON gm.group_id = g.id
            WHERE g.id = ?
            GROUP BY g.id
            """,
            (group_id,),
        )
        row = cursor.fetchone()
        return dict(row)

    return await _run_sync_db(_sync)


async def get_user_groups(telegram_id: int) -> list[dict[str, Any]]:
    def _sync(db):
        cursor = db.execute(
            """
            SELECT
                g.id,
                g.name,
                g.admin_id,
                g.created_at,
                CASE WHEN g.admin_id = ? THEN 1 ELSE 0 END AS is_owner,
                COUNT(gm_all.id) AS member_count
            FROM groups g
            JOIN group_members gm_self
                ON gm_self.group_id = g.id
               AND gm_self.telegram_id = ?
            LEFT JOIN group_members gm_all ON gm_all.group_id = g.id
            GROUP BY g.id
            ORDER BY LOWER(g.name)
            """,
            (telegram_id, telegram_id),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    return await _run_sync_db(_sync)


async def get_admin_groups(admin_id: int) -> list[dict[str, Any]]:
    def _sync(db):
        cursor = db.execute(
            """
            SELECT
                g.id,
                g.name,
                g.admin_id,
                g.created_at,
                COUNT(gm.id) AS member_count
            FROM groups g
            LEFT JOIN group_members gm ON gm.group_id = g.id
            WHERE g.admin_id = ?
            GROUP BY g.id
            ORDER BY g.created_at DESC, g.id DESC
            """,
            (admin_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    return await _run_sync_db(_sync)


async def get_group_members(group_id: int, exclude_user_id: int | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT telegram_id, username, full_name, card_number, joined_at
        FROM group_members
        WHERE group_id = ?
    """
    params: list[Any] = [group_id]
    if exclude_user_id is not None:
        query += " AND telegram_id != ?"
        params.append(exclude_user_id)
    query += " ORDER BY LOWER(COALESCE(full_name, username, CAST(telegram_id AS TEXT)))"

    def _sync(db):
        cursor = db.execute(query, tuple(params))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    members = await _run_sync_db(_sync)
    for member in members:
        member["display_name"] = _member_name(member)
    return members


async def get_group_members_in_join_order(group_id: int) -> list[dict[str, Any]]:
    def _sync(db):
        cursor = db.execute(
            """
            SELECT id, telegram_id, username, full_name, card_number, joined_at
            FROM group_members
            WHERE group_id = ?
            ORDER BY joined_at, id
            """,
            (group_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    members = await _run_sync_db(_sync)
    for member in members:
        member["display_name"] = _member_name(member)
    return members


async def get_group_members_in_trash_order(group_id: int) -> list[dict[str, Any]]:
    def _sync(db):
        _normalize_trash_order_sync(db, group_id)
        cursor = db.execute(
            """
            SELECT id, telegram_id, username, full_name, card_number, joined_at, trash_order_position
            FROM group_members
            WHERE group_id = ?
            ORDER BY trash_order_position, joined_at, id
            """,
            (group_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    members = await _run_sync_db(_sync)
    for member in members:
        member["display_name"] = _member_name(member)
    return members


async def get_group_member(group_id: int, telegram_id: int) -> dict[str, Any] | None:
    def _sync(db):
        cursor = db.execute(
            """
            SELECT telegram_id, username, full_name, card_number, joined_at
            FROM group_members
            WHERE group_id = ? AND telegram_id = ?
            """,
            (group_id, telegram_id),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    member = await _run_sync_db(_sync)
    if not member:
        return None
    member["display_name"] = _member_name(member)
    return member


async def get_group_member_display_name(
    group_id: int,
    telegram_id: int,
    fallback_full_name: str | None = None,
    fallback_username: str | None = None,
) -> str:
    member = await get_group_member(group_id, telegram_id)
    if member:
        return member["display_name"]
    return _clean_name(fallback_full_name, fallback_username, telegram_id)


async def add_member_to_group(
    group_id: int,
    telegram_id: int,
    username: str | None,
    full_name: str | None,
    card_number: str | None = None,
    prefer_new_name: bool = False,
) -> bool:
    existing = await get_group_member(group_id, telegram_id)

    def _sync(db):
        if existing:
            resolved_username = existing.get("username") or username
            if prefer_new_name and full_name:
                resolved_full_name = full_name
            else:
                resolved_full_name = existing.get("full_name") or full_name
            resolved_card_number = existing.get("card_number") or card_number
            db.execute(
                """
                UPDATE group_members
                   SET username = ?,
                       full_name = ?,
                       card_number = ?
                 WHERE group_id = ? AND telegram_id = ?
                """,
                (resolved_username, resolved_full_name, resolved_card_number, group_id, telegram_id),
            )
        else:
            next_position = _next_trash_order_position_sync(db, group_id)
            db.execute(
                """
                INSERT INTO group_members(group_id, telegram_id, username, full_name, card_number, trash_order_position)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (group_id, telegram_id, username, full_name, card_number, next_position),
            )
        db.commit()
        return existing is None

    return await _run_sync_db(_sync)


async def get_all_groups_basic() -> list[dict[str, Any]]:
    def _sync(db):
        cursor = db.execute(
            """
            SELECT id, name, created_at
            FROM groups
            ORDER BY created_at, id
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    return await _run_sync_db(_sync)


async def get_group_trash_rotation(group_id: int) -> dict[str, Any] | None:
    group = await get_group(group_id)
    if not group:
        return None

    def _sync(db):
        cursor = db.execute(
            """
            SELECT start_date
            FROM trash_rotation_settings
            WHERE group_id = ?
            """,
            (group_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    rotation = await _run_sync_db(_sync)
    start_date = _parse_date_text(rotation["start_date"]) if rotation else now_local().date()
    members = await get_group_members_in_trash_order(group_id)
    turn = _compute_trash_turn(members, start_date, now_local().date())

    assignee = turn["assignee"]
    next_assignee = turn["next_assignee"]
    next_turn_date = turn["next_turn_date"]

    return {
        "group_id": group_id,
        "group_name": group["name"],
        "start_date": _date_text(start_date),
        "is_skip_day": turn["is_skip_day"],
        "assignee_id": assignee["telegram_id"] if assignee else None,
        "assignee_name": assignee["display_name"] if assignee else None,
        "next_assignee_id": next_assignee["telegram_id"] if next_assignee else None,
        "next_assignee_name": next_assignee["display_name"] if next_assignee else None,
        "next_turn_date": _date_text(next_turn_date) if next_turn_date else None,
        "member_count": len(members),
        "order": [
            {
                "telegram_id": member["telegram_id"],
                "name": member["display_name"],
                "position": index,
            }
            for index, member in enumerate(members, start=1)
        ],
    }


async def get_today_trash_rotation(group_id: int) -> dict[str, Any] | None:
    return await get_group_trash_rotation(group_id)


async def get_today_trash_reminders() -> list[dict[str, Any]]:
    reminders: list[dict[str, Any]] = []
    groups = await get_all_groups_basic()

    for group in groups:
        rotation = await get_today_trash_rotation(group["id"])
        if not rotation or rotation["is_skip_day"] or not rotation["assignee_id"]:
            continue
        reminders.append(rotation)

    return reminders


async def remove_member_from_group(group_id: int, telegram_id: int) -> None:
    def _sync(db):
        db.execute(
            "DELETE FROM group_members WHERE group_id = ? AND telegram_id = ?",
            (group_id, telegram_id),
        )
        _normalize_trash_order_sync(db, group_id)
        db.commit()

    await _run_sync_db(_sync)


async def set_group_trash_order(group_id: int, ordered_member_ids: Sequence[int]) -> None:
    normalized_ids = [int(member_id) for member_id in ordered_member_ids]

    def _sync(db):
        cursor = db.execute(
            """
            SELECT telegram_id
            FROM group_members
            WHERE group_id = ?
            ORDER BY trash_order_position, joined_at, id
            """,
            (group_id,),
        )
        current_member_ids = [int(row["telegram_id"]) for row in cursor.fetchall()]
        if sorted(current_member_ids) != sorted(normalized_ids) or len(current_member_ids) != len(normalized_ids):
            raise ValueError("A'zolar ro'yxati o'zgargan. Iltimos, tartibni qaytadan tuzing.")

        for position, member_id in enumerate(normalized_ids, start=1):
            db.execute(
                """
                UPDATE group_members
                SET trash_order_position = ?
                WHERE group_id = ? AND telegram_id = ?
                """,
                (position, group_id, member_id),
            )
        db.commit()

    await _run_sync_db(_sync)


async def save_card_number(telegram_id: int, card_number: str) -> None:
    def _sync(db):
        db.execute(
            "UPDATE group_members SET card_number = ? WHERE telegram_id = ?",
            (card_number, telegram_id),
        )
        db.commit()

    await _run_sync_db(_sync)


async def get_saved_card(telegram_id: int) -> str | None:
    def _sync(db):
        cursor = db.execute(
            """
            SELECT card_number
            FROM group_members
            WHERE telegram_id = ? AND card_number IS NOT NULL AND TRIM(card_number) != ''
            ORDER BY joined_at DESC
            LIMIT 1
            """,
            (telegram_id,),
        )
        return cursor.fetchone()

    row = await _run_sync_db(_sync)
    return row["card_number"] if row else None


async def create_loans(
    group_id: int,
    lender_id: int,
    participant_ids: Sequence[int],
    total_amount: float,
    comment: str,
) -> list[dict[str, Any]]:
    distribution = build_loan_distribution(total_amount, participant_ids, lender_id)
    created: list[dict[str, Any]] = []

    def _sync(db):
        for allocation in distribution["borrower_allocations"]:
            borrower_id = allocation["borrower_id"]
            share = allocation["amount"]
            cursor = db.execute(
                """
                INSERT INTO loans(group_id, lender_id, borrower_id, amount, comment, status)
                VALUES (?, ?, ?, ?, ?, 'active')
                """,
                (group_id, lender_id, borrower_id, share, comment),
            )
            created.append(
                {
                    "id": cursor.lastrowid,
                    "group_id": group_id,
                    "lender_id": lender_id,
                    "borrower_id": borrower_id,
                    "amount": share,
                    "comment": comment,
                    "status": "active",
                }
            )
        db.commit()
        return created

    return await _run_sync_db(_sync)


async def get_outstanding_loans(group_id: int, lender_id: int, borrower_id: int) -> list[dict[str, Any]]:
    def _sync(db):
        cursor = db.execute(
            """
            SELECT
                l.id,
                l.group_id,
                l.lender_id,
                l.borrower_id,
                l.amount,
                l.comment,
                l.status,
                l.created_at,
                COALESCE(SUM(p.amount), 0) AS paid_amount,
                ROUND(l.amount - COALESCE(SUM(p.amount), 0), 2) AS remaining_amount
            FROM loans l
            LEFT JOIN payments p ON p.loan_id = l.id
            WHERE l.group_id = ?
              AND l.lender_id = ?
              AND l.borrower_id = ?
              AND l.status != 'cancelled'
            GROUP BY l.id
            HAVING (l.amount - COALESCE(SUM(p.amount), 0)) > 0.00001
            ORDER BY l.created_at, l.id
            """,
            (group_id, lender_id, borrower_id),
        )
        return [dict(row) for row in cursor.fetchall()]

    return await _run_sync_db(_sync)


async def get_total_outstanding(group_id: int, lender_id: int, borrower_id: int) -> float:
    loans = await get_outstanding_loans(group_id, lender_id, borrower_id)
    return _round_amount(sum(loan["remaining_amount"] for loan in loans))


async def get_net_balance(group_id: int, person_a_id: int, person_b_id: int) -> dict[str, Any]:
    person_a_owes = await get_total_outstanding(group_id, lender_id=person_b_id, borrower_id=person_a_id)
    person_b_owes = await get_total_outstanding(group_id, lender_id=person_a_id, borrower_id=person_b_id)

    net = _round_amount(person_a_owes - person_b_owes)
    if abs(net) < 0.01:
        return {
            "amount": 0.0,
            "debtor_id": None,
            "creditor_id": None,
            "direction": "settled",
        }

    if net > 0:
        return {
            "amount": net,
            "debtor_id": person_a_id,
            "creditor_id": person_b_id,
            "direction": "person_a_owes",
        }

    return {
        "amount": abs(net),
        "debtor_id": person_b_id,
        "creditor_id": person_a_id,
        "direction": "person_b_owes",
    }


async def get_user_net_balances(group_id: int, user_id: int) -> dict[str, list[dict[str, Any]]]:
    members = await get_group_members(group_id, exclude_user_id=user_id)

    you_owe: list[dict[str, Any]] = []
    people_owe_you: list[dict[str, Any]] = []

    for member in members:
        net = await get_net_balance(group_id, user_id, member["telegram_id"])
        if net["amount"] <= 0:
            continue

        entry = {
            "telegram_id": member["telegram_id"],
            "name": member["display_name"],
            "amount": net["amount"],
            "card_number": member.get("card_number"),
        }

        if net["debtor_id"] == user_id:
            you_owe.append(entry)
        else:
            people_owe_you.append(entry)

    you_owe.sort(key=lambda item: (-item["amount"], item["name"].lower()))
    people_owe_you.sort(key=lambda item: (-item["amount"], item["name"].lower()))
    return {"you_owe": you_owe, "people_owe_you": people_owe_you}


async def get_creditors_for_user(group_id: int, user_id: int) -> list[dict[str, Any]]:
    balances = await get_user_net_balances(group_id, user_id)
    return balances["you_owe"]


async def get_stats_for_user(group_id: int, user_id: int) -> dict[str, Any]:
    balances = await get_user_net_balances(group_id, user_id)

    total_loaned_out = _round_amount(sum(item["amount"] for item in balances["people_owe_you"]))
    total_you_owe = _round_amount(sum(item["amount"] for item in balances["you_owe"]))
    net_position = _round_amount(total_loaned_out - total_you_owe)

    def _sync(db):
        loaned_cursor = db.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM loans
            WHERE group_id = ? AND lender_id = ? AND status != 'cancelled'
            """,
            (group_id, user_id),
        )
        loaned_row = loaned_cursor.fetchone()

        paid_to_you_cursor = db.execute(
            """
            SELECT COALESCE(SUM(p.amount), 0) AS total
            FROM payments p
            JOIN loans l ON l.id = p.loan_id
            WHERE l.group_id = ? AND l.lender_id = ?
            """,
            (group_id, user_id),
        )
        paid_to_you_row = paid_to_you_cursor.fetchone()

        you_paid_cursor = db.execute(
            """
            SELECT COALESCE(SUM(p.amount), 0) AS total
            FROM payments p
            JOIN loans l ON l.id = p.loan_id
            WHERE l.group_id = ? AND p.payer_id = ?
            """,
            (group_id, user_id),
        )
        you_paid_row = you_paid_cursor.fetchone()

        return loaned_row, paid_to_you_row, you_paid_row

    loaned_row, paid_to_you_row, you_paid_row = await _run_sync_db(_sync)

    return {
        "you_owe": balances["you_owe"],
        "people_owe_you": balances["people_owe_you"],
        "total_loaned_out": total_loaned_out,
        "total_you_owe": total_you_owe,
        "net_position": net_position,
        "all_time_loans_given": _round_amount(loaned_row["total"]),
        "all_time_paid_to_you": _round_amount(paid_to_you_row["total"]),
        "all_time_you_paid": _round_amount(you_paid_row["total"]),
    }


async def get_stats_member_entries(group_id: int, user_id: int) -> list[dict[str, Any]]:
    members = await get_group_members(group_id, exclude_user_id=user_id)
    entries: list[dict[str, Any]] = []

    for member in members:
        net = await get_net_balance(group_id, user_id, member["telegram_id"])
        if net["direction"] == "person_a_owes":
            sort_group = 0
        elif net["direction"] == "person_b_owes":
            sort_group = 1
        else:
            sort_group = 2

        entries.append(
            {
                "telegram_id": member["telegram_id"],
                "name": member["display_name"],
                "net": net,
                "sort_group": sort_group,
            }
        )

    entries.sort(
        key=lambda item: (
            item["sort_group"],
            -item["net"]["amount"],
            item["name"].lower(),
        )
    )
    return entries


async def get_pair_transaction_history(
    group_id: int,
    user_id: int,
    other_id: int,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
) -> dict[str, Any] | None:
    other_member = await get_group_member(group_id, other_id)
    if not other_member:
        return None

    loans_query = """
        SELECT
            l.id,
            l.created_at,
            l.amount,
            l.comment,
            l.status,
            l.lender_id,
            l.borrower_id,
            COALESCE(SUM(p.amount), 0) AS paid_amount,
            ROUND(l.amount - COALESCE(SUM(p.amount), 0), 2) AS remaining_amount,
            lender.full_name AS lender_full_name,
            lender.username AS lender_username,
            borrower.full_name AS borrower_full_name,
            borrower.username AS borrower_username
        FROM loans l
        LEFT JOIN payments p ON p.loan_id = l.id
        LEFT JOIN group_members lender
            ON lender.group_id = l.group_id AND lender.telegram_id = l.lender_id
        LEFT JOIN group_members borrower
            ON borrower.group_id = l.group_id AND borrower.telegram_id = l.borrower_id
        WHERE l.group_id = ?
          AND (
                (l.lender_id = ? AND l.borrower_id = ?)
             OR (l.lender_id = ? AND l.borrower_id = ?)
          )
    """
    payments_query = """
        SELECT
            p.id,
            p.loan_id,
            p.payer_id,
            p.amount,
            p.proof_type,
            p.proof_content,
            p.note,
            p.approved_at,
            l.lender_id,
            l.borrower_id,
            payer.full_name AS payer_full_name,
            payer.username AS payer_username,
            lender.full_name AS lender_full_name,
            lender.username AS lender_username
        FROM payments p
        JOIN loans l ON l.id = p.loan_id
        LEFT JOIN group_members payer
            ON payer.group_id = l.group_id AND payer.telegram_id = p.payer_id
        LEFT JOIN group_members lender
            ON lender.group_id = l.group_id AND lender.telegram_id = l.lender_id
        WHERE l.group_id = ?
          AND (
                (l.lender_id = ? AND l.borrower_id = ?)
             OR (l.lender_id = ? AND l.borrower_id = ?)
          )
    """

    params: list[Any] = [group_id, user_id, other_id, other_id, user_id]
    payment_params: list[Any] = [group_id, user_id, other_id, other_id, user_id]

    if start_utc is not None:
        start_text = start_utc.strftime("%Y-%m-%d %H:%M:%S")
        loans_query += " AND l.created_at >= ?"
        payments_query += " AND p.approved_at >= ?"
        params.append(start_text)
        payment_params.append(start_text)

    if end_utc is not None:
        end_text = end_utc.strftime("%Y-%m-%d %H:%M:%S")
        loans_query += " AND l.created_at <= ?"
        payments_query += " AND p.approved_at <= ?"
        params.append(end_text)
        payment_params.append(end_text)

    loans_query += " GROUP BY l.id ORDER BY l.created_at DESC, l.id DESC"
    payments_query += " ORDER BY p.approved_at DESC, p.id DESC"

    def _sync(db):
        loan_cursor = db.execute(loans_query, tuple(params))
        payment_cursor = db.execute(payments_query, tuple(payment_params))
        return loan_cursor.fetchall(), payment_cursor.fetchall()

    loan_rows, payment_rows = await _run_sync_db(_sync)
    current_net = await get_net_balance(group_id, user_id, other_id)

    transactions: list[dict[str, Any]] = []
    totals = {
        "loans_you_gave": 0.0,
        "loans_you_received": 0.0,
        "payments_you_made": 0.0,
        "payments_you_received": 0.0,
    }

    for row in loan_rows:
        item = dict(row)
        lender_name = _clean_name(item["lender_full_name"], item["lender_username"], item["lender_id"])
        borrower_name = _clean_name(item["borrower_full_name"], item["borrower_username"], item["borrower_id"])
        you_are_lender = item["lender_id"] == user_id

        if you_are_lender:
            totals["loans_you_gave"] += float(item["amount"])
            title = f"Siz {borrower_name} ga qarz berdingiz"
        else:
            totals["loans_you_received"] += float(item["amount"])
            title = f"{lender_name} sizga qarz berdi"

        transactions.append(
            {
                "kind": "loan",
                "timestamp": item["created_at"],
                "amount": _round_amount(item["amount"]),
                "title": title,
                "comment": item["comment"],
                "status": item["status"],
                "remaining_amount": _round_amount(item["remaining_amount"]),
                "paid_amount": _round_amount(item["paid_amount"]),
            }
        )

    for row in payment_rows:
        item = dict(row)
        payer_name = _clean_name(item["payer_full_name"], item["payer_username"], item["payer_id"])
        lender_name = _clean_name(item["lender_full_name"], item["lender_username"], item["lender_id"])
        you_are_payer = item["payer_id"] == user_id

        if you_are_payer:
            totals["payments_you_made"] += float(item["amount"])
            title = f"Siz {lender_name} ga to'lov qildingiz"
        else:
            totals["payments_you_received"] += float(item["amount"])
            title = f"{payer_name} sizga to'lov qildi"

        transactions.append(
            {
                "kind": "payment",
                "timestamp": item["approved_at"],
                "amount": _round_amount(item["amount"]),
                "title": title,
                "note": item.get("note"),
                "proof_type": item["proof_type"],
                "proof_content": item["proof_content"],
            }
        )

    transactions.sort(key=lambda item: item["timestamp"], reverse=True)

    for key, value in totals.items():
        totals[key] = _round_amount(value)

    return {
        "member_id": other_id,
        "member_name": other_member["display_name"],
        "current_net": current_net,
        "totals": totals,
        "transactions": transactions,
    }


async def record_payment(
    group_id: int,
    payer_id: int,
    creditor_id: int,
    amount: float,
    proof_type: str,
    proof_content: str,
    note: str | None = None,
) -> list[dict[str, Any]]:
    remaining_to_allocate = _round_amount(amount)
    allocations: list[dict[str, Any]] = []

    def _sync(db):
        cursor = db.execute(
            """
            SELECT
                l.id,
                l.amount,
                l.comment,
                COALESCE(SUM(p.amount), 0) AS paid_amount
            FROM loans l
            LEFT JOIN payments p ON p.loan_id = l.id
            WHERE l.group_id = ?
              AND l.lender_id = ?
              AND l.borrower_id = ?
              AND l.status != 'cancelled'
            GROUP BY l.id
            HAVING (l.amount - COALESCE(SUM(p.amount), 0)) > 0.00001
            ORDER BY l.created_at, l.id
            """,
            (group_id, creditor_id, payer_id),
        )
        loans = cursor.fetchall()

        if not loans:
            raise ValueError("Bu to'lov uchun faol qarz topilmadi.")

        for loan in loans:
            nonlocal remaining_to_allocate
            if remaining_to_allocate <= 0:
                break

            loan_remaining = _round_amount(loan["amount"] - loan["paid_amount"])
            allocated = min(remaining_to_allocate, loan_remaining)
            if allocated <= 0:
                continue

            payment_cursor = db.execute(
                """
                INSERT INTO payments(loan_id, payer_id, amount, proof_type, proof_content, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    loan["id"],
                    payer_id,
                    allocated,
                    proof_type,
                    proof_content,
                    note,
                ),
            )

            new_remaining = _round_amount(loan_remaining - allocated)
            new_status = "paid" if new_remaining <= 0 else "active"
            db.execute(
                "UPDATE loans SET status = ? WHERE id = ?",
                (new_status, loan["id"]),
            )

            allocations.append(
                {
                    "payment_id": payment_cursor.lastrowid,
                    "loan_id": loan["id"],
                    "amount": allocated,
                    "comment": loan["comment"],
                }
            )
            remaining_to_allocate = _round_amount(remaining_to_allocate - allocated)

        if remaining_to_allocate > 0:
            raise ValueError("To'lov miqdori joriy qarzdan katta.")

        db.commit()
        return allocations

    return await _run_sync_db(_sync)


async def get_group_active_total(group_id: int) -> float:
    def _sync(db):
        cursor = db.execute(
            """
            SELECT COALESCE(SUM(remaining_amount), 0) AS total
            FROM (
                SELECT
                    ROUND(l.amount - COALESCE(SUM(p.amount), 0), 2) AS remaining_amount
                FROM loans l
                LEFT JOIN payments p ON p.loan_id = l.id
                WHERE l.group_id = ? AND l.status != 'cancelled'
                GROUP BY l.id
                HAVING (l.amount - COALESCE(SUM(p.amount), 0)) > 0.00001
            )
            """,
            (group_id,),
        )
        row = cursor.fetchone()
        return _round_amount(row["total"] if row else 0)

    return await _run_sync_db(_sync)


async def get_groups_overview(admin_id: int) -> list[dict[str, Any]]:
    groups = await get_admin_groups(admin_id)
    for group in groups:
        group["active_total"] = await get_group_active_total(group["id"])
    return groups


async def get_history_records(
    group_id: int,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    loans_query = """
        SELECT
            l.id,
            l.created_at,
            l.amount,
            l.comment,
            l.status,
            l.lender_id,
            l.borrower_id,
            lender.full_name AS lender_full_name,
            lender.username AS lender_username,
            borrower.full_name AS borrower_full_name,
            borrower.username AS borrower_username
        FROM loans l
        LEFT JOIN group_members lender
            ON lender.group_id = l.group_id AND lender.telegram_id = l.lender_id
        LEFT JOIN group_members borrower
            ON borrower.group_id = l.group_id AND borrower.telegram_id = l.borrower_id
        WHERE l.group_id = ?
    """
    payments_query = """
        SELECT
            p.id,
            p.loan_id,
            p.payer_id,
            p.amount,
            p.proof_type,
            p.proof_content,
            p.note,
            p.approved_at,
            l.lender_id,
            payer.full_name AS payer_full_name,
            payer.username AS payer_username,
            lender.full_name AS lender_full_name,
            lender.username AS lender_username
        FROM payments p
        JOIN loans l ON l.id = p.loan_id
        LEFT JOIN group_members payer
            ON payer.group_id = l.group_id AND payer.telegram_id = p.payer_id
        LEFT JOIN group_members lender
            ON lender.group_id = l.group_id AND lender.telegram_id = l.lender_id
        WHERE l.group_id = ?
    """

    params: list[Any] = [group_id]
    payment_params: list[Any] = [group_id]

    if start_utc is not None:
        start_text = start_utc.strftime("%Y-%m-%d %H:%M:%S")
        loans_query += " AND l.created_at >= ?"
        payments_query += " AND p.approved_at >= ?"
        params.append(start_text)
        payment_params.append(start_text)

    if end_utc is not None:
        end_text = end_utc.strftime("%Y-%m-%d %H:%M:%S")
        loans_query += " AND l.created_at <= ?"
        payments_query += " AND p.approved_at <= ?"
        params.append(end_text)
        payment_params.append(end_text)

    loans_query += " ORDER BY l.created_at, l.id"
    payments_query += " ORDER BY p.approved_at, p.id"

    def _sync(db):
        loan_cursor = db.execute(loans_query, tuple(params))
        payment_cursor = db.execute(payments_query, tuple(payment_params))
        return loan_cursor.fetchall(), payment_cursor.fetchall()

    loan_rows, payment_rows = await _run_sync_db(_sync)

    loans: list[dict[str, Any]] = []
    for row in loan_rows:
        item = dict(row)
        item["from_name"] = _clean_name(item["lender_full_name"], item["lender_username"], item["lender_id"])
        item["to_name"] = _clean_name(item["borrower_full_name"], item["borrower_username"], item["borrower_id"])
        loans.append(item)

    payments: list[dict[str, Any]] = []
    for row in payment_rows:
        item = dict(row)
        item["from_name"] = _clean_name(item["payer_full_name"], item["payer_username"], item["payer_id"])
        item["to_name"] = _clean_name(item["lender_full_name"], item["lender_username"], item["lender_id"])
        payments.append(item)

    return {"loans": loans, "payments": payments}
