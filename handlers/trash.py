from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import queries
from keyboards import menus


router = Router(name="trash")
logger = logging.getLogger(__name__)


def _trash_turn_text(rotation: dict[str, Any], viewer_id: int) -> str:
    if rotation["member_count"] <= 0:
        return f"🗑 {rotation['group_name']} guruhida hali navbat uchun a'zolar yo'q."

    if rotation["is_skip_day"]:
        text = (
            f"🗑 {rotation['group_name']} guruhida bugun musor navbat yo'q.\n\n"
            "Bugun dam kuni."
        )
        if rotation["next_assignee_name"] and rotation["next_turn_date"]:
            text += (
                f"\n\nKeyingi navbat: {rotation['next_assignee_name']}"
                f"\nSana: {rotation['next_turn_date']}"
            )
        return text

    assignee_name = "Siz" if rotation["assignee_id"] == viewer_id else rotation["assignee_name"]
    text = (
        f"🗑 {rotation['group_name']} guruhida bugungi musor navbat:\n\n"
        f"{assignee_name}"
    )

    if rotation["next_assignee_name"] and rotation["next_turn_date"]:
        text += (
            f"\n\nKeyingi navbat: {rotation['next_assignee_name']}"
            f"\nSana: {rotation['next_turn_date']}"
        )

    return text


async def _send_trash_turn(
    target: Message | CallbackQuery,
    viewer_id: int,
    group_id: int,
) -> None:
    rotation = await queries.get_today_trash_rotation(group_id)
    if not rotation:
        text = "⚠️ Bu guruh topilmadi."
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return

    text = _trash_turn_text(rotation, viewer_id)
    markup = menus.back_to_menu_inline()

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup)
        await target.answer()
        return

    await target.answer(text, reply_markup=markup)


@router.message(F.text == "🗑 Musor Navbat", flags={"member_required": True})
async def trash_turn_entry(
    message: Message,
    state: FSMContext,
    user_groups: list[dict[str, Any]],
) -> None:
    await state.clear()
    if len(user_groups) == 1:
        await _send_trash_turn(message, message.from_user.id, user_groups[0]["id"])
        return

    await message.answer(
        "🗑 Musor navbatini ko'rish uchun guruhni tanlang:",
        reply_markup=menus.group_selection_keyboard(user_groups, "trash_group"),
    )


@router.callback_query(F.data.startswith("trash_group:"), flags={"member_required": True})
async def trash_turn_group_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    group_id = int(callback.data.split(":")[1])
    await _send_trash_turn(callback, callback.from_user.id, group_id)


async def send_daily_trash_reminders(bot: Bot) -> None:
    reminders = await queries.get_today_trash_reminders()
    if not reminders:
        return

    for reminder in reminders:
        try:
            await bot.send_message(
                chat_id=reminder["assignee_id"],
                text=(
                    f"🗑 Eslatma: bugun {reminder['group_name']} guruhida musor navbat sizda.\n"
                    "Iltimos, chiqindini olib chiqishni unutmang."
                ),
            )
        except TelegramForbiddenError:
            logger.info(
                "Trash reminder skipped for %s in group %s: bot is blocked or chat is unavailable.",
                reminder["assignee_id"],
                reminder["group_id"],
            )
        except TelegramAPIError:
            logger.exception(
                "Failed to send trash reminder to %s for group %s",
                reminder["assignee_id"],
                reminder["group_id"],
            )
