from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from db import queries
from keyboards import menus
from utils.export import build_history_text
from utils.formatters import format_timestamp, get_period_bounds, sanitize_filename, to_utc


router = Router(name="history")


async def _ask_period(target: Message | CallbackQuery, group_id: int) -> None:
    group = await queries.get_group(group_id)
    if not group:
        text = "⚠️ Ushbu guruhni topa olmadim."
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(
            f"📋 {group['name']} tarixi\n\nDavrni tanlang:",
            reply_markup=menus.history_period_keyboard(group_id),
        )
        await target.answer()
        return

    await target.answer(
        f"📋 {group['name']} tarixi\n\nDavrni tanlang:",
        reply_markup=menus.history_period_keyboard(group_id),
    )


@router.message(F.text == "📋 Tarix", flags={"member_required": True})
async def history_entry(
    message: Message,
    state: FSMContext,
    user_groups: list[dict[str, int | str]],
) -> None:
    await state.clear()
    if len(user_groups) == 1:
        await _ask_period(message, user_groups[0]["id"])
        return

    await message.answer(
        "📋 Tarix hisobotini olish uchun guruhni tanlang:",
        reply_markup=menus.group_selection_keyboard(user_groups, "history_group"),
    )


@router.callback_query(F.data.startswith("history_group:"), flags={"member_required": True})
async def history_group_callback(callback: CallbackQuery) -> None:
    group_id = int(callback.data.split(":")[1])
    await _ask_period(callback, group_id)


@router.callback_query(F.data.startswith("history_period:"), flags={"member_required": True})
async def history_period_callback(callback: CallbackQuery) -> None:
    _, group_id_text, period = callback.data.split(":")
    group_id = int(group_id_text)
    group = await queries.get_group(group_id)
    if not group:
        await callback.answer("⚠️ Bu guruh endi topilmadi.", show_alert=True)
        return

    period_label, start_local, end_local = get_period_bounds(period)
    start_utc = to_utc(start_local)
    end_utc = to_utc(end_local)
    records = await queries.get_history_records(group_id, start_utc=start_utc, end_utc=end_utc)

    start_text = format_timestamp(start_utc) if start_utc else "Boshlanishidan"
    end_text = format_timestamp(end_utc) if end_utc else "Hozirgacha"
    history_text = build_history_text(group["name"], period_label, start_text, end_text, records)

    period_filename = {
        "today": "bugun",
        "week": "shu_hafta",
        "month": "shu_oy",
        "all": "barcha_vaqt",
    }.get(period, period)
    filename = f"tarix_{sanitize_filename(group['name'])}_{period_filename}.txt"
    document = BufferedInputFile(history_text.encode("utf-8"), filename=filename)

    await callback.message.edit_text("⏳ Jarayon...")
    await callback.message.answer_document(document=document)
    await callback.message.answer(
        "✅ Tarix eksporti tayyor.",
        reply_markup=menus.back_to_menu_inline(),
    )
    await callback.answer()
