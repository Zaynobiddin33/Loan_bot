from __future__ import annotations

from contextlib import suppress
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import queries
from keyboards import menus
from states import CardStates
from utils.formatters import format_amount


router = Router(name="stats")


async def _build_menu_text(user_id: int, is_admin: bool, user_groups: list[dict[str, Any]]) -> str:
    if not user_groups and not is_admin:
        return (
            "👋 Qarzni kuzatuvchi botga xush kelibsiz.\n\n"
            "Bu bot kichik ishonchli guruhlarga kim pul berdi, kim hali qarzdor va nima to'langanini kuzatishda yordam beradi.\n\n"
            "Avvalo guruh adminidan sizni qo'shishini so'rang, so'ng /start ni qayta yuboring."
        )

    lines = []
    if user_groups:
        lines.append("👋 Yana xush kelibsiz.")
        lines.append("")
        lines.append("Sizning guruhlaringiz:")
        for group in user_groups:
            role = "egasi" if group["is_owner"] else "a'zo"
            lines.append(f"• {group['name']} ({group['member_count']} a'zo, {role})")
    else:
        lines.append("👋 Yana xush kelibsiz.")
        lines.append("")
        lines.append("Siz quyidagi admin panel orqali birinchi guruhni yaratish bilan boshlashingiz mumkin.")

    if is_admin:
        lines.append("")
        lines.append("Admin vositalari asosiy menyu ustida mavjud.")

    return "\n".join(lines)


async def show_main_menu(
    target: Message | CallbackQuery,
    user_id: int,
    note: str | None = None,
) -> None:
    is_admin = await queries.is_admin(user_id)
    user_groups = await queries.get_user_groups(user_id)
    text = await _build_menu_text(user_id, is_admin, user_groups)
    if note:
        text = f"{note}\n\n{text}"

    if isinstance(target, CallbackQuery):
        with suppress(TelegramBadRequest):
            await target.message.edit_reply_markup(reply_markup=None)
        await target.message.answer(text, reply_markup=menus.main_menu_keyboard(is_admin=is_admin))
        return

    await target.answer(text, reply_markup=menus.main_menu_keyboard(is_admin=is_admin))


def _stats_text(group_name: str, stats: dict[str, Any]) -> str:
    you_owe_lines = (
        "\n".join(f"  • {item['name']}: {format_amount(item['amount'])}" for item in stats["you_owe"])
        if stats["you_owe"]
        else "  • Hozircha qarzingiz yo'q"
    )
    people_owe_lines = (
        "\n".join(f"  • {item['name']}: {format_amount(item['amount'])}" for item in stats["people_owe_you"])
        if stats["people_owe_you"]
        else "  • Hozircha sizga hech kim qarzdor emas"
    )

    if stats["net_position"] > 0:
        net_line = f"+{format_amount(stats['net_position'])} sizga berilishi kerak"
    elif stats["net_position"] < 0:
        net_line = f"-{format_amount(abs(stats['net_position']))} siz qarzdorsiz"
    else:
        net_line = "0 hisob-kitob yopilgan"

    return (
        f"📊 {group_name} guruhidagi statistikangiz\n\n"
        f"💸 Siz bergan qarzlar jami: {format_amount(stats['total_loaned_out'])}\n"
        f"💰 Sizning qarzlaringiz jami: {format_amount(stats['total_you_owe'])}\n"
        f"📈 Sof holat: {net_line}\n\n"
        "--- Tafsilotlar ---\n\n"
        f"Siz qarzdorsiz:\n{you_owe_lines}\n\n"
        f"Sizga qarzdorlar:\n{people_owe_lines}\n\n"
        "--- Umumiy tarix ---\n"
        f"Siz bergan qarzlar jami: {format_amount(stats['all_time_loans_given'])}\n"
        f"Sizga to'langan summa jami: {format_amount(stats['all_time_paid_to_you'])}\n"
        f"Siz to'lagan summa jami: {format_amount(stats['all_time_you_paid'])}\n\n"
        "Karta raqamini ko'rish uchun pastdagi ismni bosing."
    )


async def _send_stats(target: Message | CallbackQuery, user_id: int, group_id: int) -> None:
    group = await queries.get_group(group_id)
    if not group:
        text = "⚠️ Bu guruh endi topilmadi. Iltimos, qayta urinib ko'ring."
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return

    stats = await queries.get_stats_for_user(group_id, user_id)
    card_entries = stats["you_owe"] + stats["people_owe_you"]
    keyboard = menus.stats_card_keyboard(card_entries)
    text = _stats_text(group["name"], stats)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=keyboard)
        await target.answer()
        return

    await target.answer(text, reply_markup=keyboard)


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_main_menu(message, message.from_user.id)


@router.message(F.text == "🏠 Menyuga qaytish")
async def back_to_menu_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_main_menu(message, message.from_user.id)


@router.message(F.text == "❌ Bekor qilish")
async def cancel_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_main_menu(message, message.from_user.id, note="❌ Amal bekor qilindi.")


@router.callback_query(F.data == "cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Bekor qilindi")
    await show_main_menu(callback, callback.from_user.id, note="❌ Amal bekor qilindi.")


@router.callback_query(F.data == "back_menu")
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await show_main_menu(callback, callback.from_user.id)


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(F.text == "👥 Guruhlarim", flags={"member_required": True})
async def my_groups_handler(
    message: Message,
    state: FSMContext,
    user_groups: list[dict[str, Any]],
) -> None:
    await state.clear()
    lines = ["👥 Sizning guruhlaringiz", ""]
    for group in user_groups:
        role = "egasi" if group["is_owner"] else "a'zo"
        lines.append(f"• {group['name']} ({group['member_count']} a'zo, {role})")

    await message.answer("\n".join(lines))


@router.message(F.text == "📊 Statistikam", flags={"member_required": True})
async def stats_entry_handler(
    message: Message,
    state: FSMContext,
    user_groups: list[dict[str, Any]],
) -> None:
    await state.clear()
    if len(user_groups) == 1:
        await _send_stats(message, message.from_user.id, user_groups[0]["id"])
        return

    await message.answer(
        "📊 Statistikani ko'rish uchun guruhni tanlang:",
        reply_markup=menus.group_selection_keyboard(user_groups, "stats_group"),
    )


@router.callback_query(F.data.startswith("stats_group:"), flags={"member_required": True})
async def stats_group_callback(callback: CallbackQuery) -> None:
    group_id = int(callback.data.split(":")[1])
    await _send_stats(callback, callback.from_user.id, group_id)


@router.callback_query(F.data.startswith("stats_card:"), flags={"member_required": True})
async def stats_card_callback(callback: CallbackQuery) -> None:
    telegram_id = int(callback.data.split(":")[1])
    card = await queries.get_saved_card(telegram_id)
    if card:
        await callback.answer(f"💳 Karta raqami: {card}", show_alert=True)
    else:
        await callback.answer("💳 Ushbu foydalanuvchi hali karta raqamini qo'shmagan.", show_alert=True)


@router.message(F.text == "💳 Kartam", flags={"member_required": True})
async def my_card_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    current_card = await queries.get_saved_card(message.from_user.id)
    if current_card:
        text = f"💳 Sizning kartangiz: {current_card}\n\nAgar yangilamoqchi bo'lsangiz, quyidagiga bosing."
    else:
        text = "💳 Siz hali karta qo'shmadingiz.\n\nUni saqlash uchun quyidagiga bosing."

    await message.answer(text, reply_markup=menus.card_update_keyboard())


@router.callback_query(F.data == "card_update", flags={"member_required": True})
async def card_update_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CardStates.enter_card)
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Karta raqamingizni kiriting:",
        reply_markup=menus.cancel_reply_keyboard(),
    )
    await callback.answer()


@router.message(CardStates.enter_card)
async def save_card_handler(message: Message, state: FSMContext) -> None:
    card_number = (message.text or "").strip()
    if not card_number:
        await message.answer("⚠️ Iltimos, karta raqamini yuboring yoki ❌ Bekor qilishni bosing.")
        return

    await queries.save_card_number(message.from_user.id, card_number)
    await state.clear()

    digits_count = sum(character.isdigit() for character in card_number)
    warning = ""
    if digits_count < 8:
        warning = "⚠️ Bu format noodatiy ko'rinadi, lekin baribir saqlandi.\n\n"

    is_admin = await queries.is_admin(message.from_user.id)
    await message.answer(
        f"{warning}✅ Karta raqamingiz saqlandi.",
        reply_markup=menus.main_menu_keyboard(is_admin=is_admin),
    )
