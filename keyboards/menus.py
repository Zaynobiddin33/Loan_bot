from __future__ import annotations

from typing import Any

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.formatters import format_amount


MEMBER_PAGE_SIZE = 8


def main_menu_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []

    if is_admin:
        rows.extend(
            [
                [KeyboardButton(text="➕ Guruh yaratish"), KeyboardButton(text="👤 A'zo qo'shish")],
                [KeyboardButton(text="🗑 A'zoni o'chirish"), KeyboardButton(text="🔁 Musor tartibi")],
                [KeyboardButton(text="📋 Guruhlar")],
            ]
        )

    rows.extend(
        [
            [KeyboardButton(text="💸 Qarzni berish"), KeyboardButton(text="💰 Qarzni to'lash")],
            [KeyboardButton(text="📊 Statistikam"), KeyboardButton(text="📋 Tarix")],
            [KeyboardButton(text="💳 Kartam"), KeyboardButton(text="👥 Guruhlarim")],
            [KeyboardButton(text="🗑 Musor Navbat")],
        ]
    )

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def back_to_menu_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🏠 Menyuga qaytish", callback_data="back_menu")]]
    )


def confirmation_keyboard(confirm_data: str, cancel_data: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=confirm_data),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data=cancel_data),
            ]
        ]
    )


def group_selection_keyboard(
    groups: list[dict[str, Any]],
    prefix: str,
    include_cancel: bool = True,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for group in groups:
        builder.button(text=group["name"], callback_data=f"{prefix}:{group['id']}")
    builder.adjust(1)

    if include_cancel:
        builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel"))

    return builder.as_markup()


def borrower_selection_keyboard(
    members: list[dict[str, Any]],
    selected_ids: set[int],
    page: int,
) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(members) - 1) // MEMBER_PAGE_SIZE + 1)
    page = max(0, min(page, total_pages - 1))
    start = page * MEMBER_PAGE_SIZE
    page_members = members[start : start + MEMBER_PAGE_SIZE]

    builder = InlineKeyboardBuilder()
    all_member_ids = {member["telegram_id"] for member in members}
    all_selected = bool(members) and selected_ids == all_member_ids
    all_icon = "✅" if all_selected else "⬜️"
    builder.button(text=f"{all_icon} Barcha a'zolar", callback_data=f"loan_toggle_all:{page}")

    for member in page_members:
        icon = "✅" if member["telegram_id"] in selected_ids else "⬜️"
        builder.button(
            text=f"{icon} {member.get('selection_name', member['display_name'])}",
            callback_data=f"loan_toggle_member:{member['telegram_id']}:{page}",
        )

    builder.adjust(1)

    if total_pages > 1:
        builder.row(
            InlineKeyboardButton(text="⬅️", callback_data=f"loan_page:{page - 1}"),
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="➡️", callback_data=f"loan_page:{page + 1}"),
        )

    if selected_ids:
        builder.row(InlineKeyboardButton(text="➡️ Davom etish", callback_data="loan_continue"))

    builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel"))
    return builder.as_markup()


def creditor_keyboard(creditors: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for creditor in creditors:
        builder.button(
            text=f"{creditor['name']} — siz qarzdorsiz {format_amount(creditor['amount'])}",
            callback_data=f"payment_creditor:{creditor['telegram_id']}",
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel"))
    return builder.as_markup()


def history_period_keyboard(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Bugun", callback_data=f"history_period:{group_id}:today"),
                InlineKeyboardButton(text="📅 Bu hafta", callback_data=f"history_period:{group_id}:week"),
            ],
            [
                InlineKeyboardButton(text="📅 Bu oy", callback_data=f"history_period:{group_id}:month"),
                InlineKeyboardButton(text="📅 Barcha davr", callback_data=f"history_period:{group_id}:all"),
            ],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel")],
        ]
    )


def remove_member_keyboard(group_id: int, members: list[dict[str, Any]], page: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(members) - 1) // MEMBER_PAGE_SIZE + 1)
    page = max(0, min(page, total_pages - 1))
    start = page * MEMBER_PAGE_SIZE
    page_members = members[start : start + MEMBER_PAGE_SIZE]

    builder = InlineKeyboardBuilder()
    for member in page_members:
        builder.button(
            text=member["display_name"],
            callback_data=f"admin_pick_remove:{group_id}:{member['telegram_id']}",
        )
    builder.adjust(1)

    if total_pages > 1:
        builder.row(
            InlineKeyboardButton(text="⬅️", callback_data=f"admin_remove_page:{group_id}:{page - 1}"),
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="➡️", callback_data=f"admin_remove_page:{group_id}:{page + 1}"),
        )

    builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel"))
    return builder.as_markup()


def trash_order_keyboard(
    members: list[dict[str, Any]],
    selected_ids: list[int],
    page: int,
) -> InlineKeyboardMarkup:
    selected_set = set(selected_ids)
    remaining_members = [member for member in members if member["telegram_id"] not in selected_set]

    total_pages = max(1, (len(remaining_members) - 1) // MEMBER_PAGE_SIZE + 1)
    page = max(0, min(page, total_pages - 1))
    start = page * MEMBER_PAGE_SIZE
    page_members = remaining_members[start : start + MEMBER_PAGE_SIZE]

    builder = InlineKeyboardBuilder()
    for member in page_members:
        builder.button(
            text=member["display_name"],
            callback_data=f"admin_trash_pick:{member['telegram_id']}:{page}",
        )
    builder.adjust(1)

    if total_pages > 1:
        builder.row(
            InlineKeyboardButton(text="⬅️", callback_data=f"admin_trash_page:{page - 1}"),
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="➡️", callback_data=f"admin_trash_page:{page + 1}"),
        )

    if selected_ids:
        builder.row(
            InlineKeyboardButton(text="↩️ Oxirgisini olib tashlash", callback_data="admin_trash_undo"),
            InlineKeyboardButton(text="🔄 Boshidan", callback_data="admin_trash_reset"),
        )

    if not remaining_members and members:
        builder.row(InlineKeyboardButton(text="✅ Saqlash", callback_data="admin_trash_save"))

    builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel"))
    return builder.as_markup()


def card_update_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Kartani yangilash", callback_data="card_update")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel")],
        ]
    )


def stats_card_keyboard(entries: list[dict[str, Any]]) -> InlineKeyboardMarkup | None:
    if not entries:
        return None

    builder = InlineKeyboardBuilder()
    for entry in entries:
        builder.button(text=f"💳 {entry['name']}", callback_data=f"stats_card:{entry['telegram_id']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🏠 Menyuga qaytish", callback_data="back_menu"))
    return builder.as_markup()
