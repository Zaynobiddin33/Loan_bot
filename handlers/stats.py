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
from utils.formatters import format_amount, format_timestamp, get_period_bounds, to_utc


router = Router(name="stats")
PAIR_HISTORY_LIMIT = 12


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

    member_note = (
        "Pastdagi a'zolardan birini tanlang. Men siz bilan u o'rtasidagi tranzaksiyalarni ko'rsataman."
        if stats["member_entries"]
        else "Bu guruhda sizdan boshqa a'zo yo'q."
    )

    return (
        f"📊 {group_name} guruhidagi holatingiz\n\n"
        f"💸 Sizga qarzdorlar jami: {format_amount(stats['total_loaned_out'])}\n"
        f"💰 Siz qarzdor bo'lganlar jami: {format_amount(stats['total_you_owe'])}\n"
        f"📈 Sof holat: {net_line}\n\n"
        "--- Hozirgi balans ---\n\n"
        f"Siz qarzdorsiz:\n{you_owe_lines}\n\n"
        f"Sizga qarzdorlar:\n{people_owe_lines}\n\n"
        "--- Umumiy ko'rsatkichlar ---\n"
        f"Siz bergan qarzlar jami: {format_amount(stats['all_time_loans_given'])}\n"
        f"Sizga to'langan summa jami: {format_amount(stats['all_time_paid_to_you'])}\n"
        f"Siz to'lagan summa jami: {format_amount(stats['all_time_you_paid'])}\n\n"
        f"{member_note}"
    )


def _member_button_text(entry: dict[str, Any]) -> str:
    net = entry["net"]
    short_name = _truncate_text(entry["name"], limit=24)
    if net["direction"] == "person_a_owes":
        return f"⬇️ {short_name} — siz qarzdorsiz {format_amount(net['amount'])}"
    if net["direction"] == "person_b_owes":
        return f"⬆️ {short_name} — sizga {format_amount(net['amount'])}"
    return f"➖ {short_name} — yopilgan"


def _current_net_text(member_name: str, net: dict[str, Any]) -> str:
    if net["direction"] == "person_a_owes":
        return f"Siz {member_name} ga {format_amount(net['amount'])} qarzdorsiz."
    if net["direction"] == "person_b_owes":
        return f"{member_name} sizga {format_amount(net['amount'])} qarzdor."
    return f"Siz bilan {member_name} orasidagi hisob-kitob hozircha yopilgan."


def _loan_status_text(item: dict[str, Any]) -> str:
    if item["status"] == "paid":
        return "yopilgan"
    if item["status"] == "cancelled":
        return "bekor qilingan"
    if item["remaining_amount"] > 0:
        return f"{format_amount(item['remaining_amount'])} qoldi"
    return "faol"


def _proof_text(item: dict[str, Any]) -> str:
    if item.get("proof_type") == "image":
        if item.get("note"):
            return f"Skrinshot ({_truncate_text(item['note'])})"
        return "Skrinshot"
    if item.get("proof_type") == "text":
        return _truncate_text(item.get("proof_content") or "Matnli eslatma")
    return "Dalil yo'q"


def _truncate_text(text: str | None, limit: int = 90) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def _pair_history_text(
    group_name: str,
    member_name: str,
    period_label: str,
    start_text: str,
    end_text: str,
    history: dict[str, Any],
) -> str:
    transactions = history["transactions"]
    shown_transactions = transactions[:PAIR_HISTORY_LIMIT]

    lines = [
        f"📘 {member_name} bilan tranzaksiyalar",
        f"Guruh: {group_name}",
        f"Davr: {period_label}",
        f"Oraliq: {start_text} dan {end_text} gacha",
        "",
        f"Joriy holat: {_current_net_text(member_name, history['current_net'])}",
        "",
        "--- Davr bo'yicha ---",
        f"Siz bergan qarzlar: {format_amount(history['totals']['loans_you_gave'])}",
        f"Siz olgan qarzlar: {format_amount(history['totals']['loans_you_received'])}",
        f"Siz to'lagan: {format_amount(history['totals']['payments_you_made'])}",
        f"Sizga to'langan: {format_amount(history['totals']['payments_you_received'])}",
        "",
    ]

    if not shown_transactions:
        lines.append("Bu davrda tranzaksiya topilmadi.")
        return "\n".join(lines)

    lines.append("--- Tranzaksiyalar ---")
    for item in shown_transactions:
        if item["kind"] == "loan":
            lines.extend(
                [
                    f"• {format_timestamp(item['timestamp'])} | Qarz | {item['title']}",
                    f"  Summa: {format_amount(item['amount'])}",
                    f"  Holat: {_loan_status_text(item)}",
                ]
            )
            if item.get("comment"):
                lines.append(f"  Izoh: {_truncate_text(item['comment'])}")
        else:
            lines.extend(
                [
                    f"• {format_timestamp(item['timestamp'])} | To'lov | {item['title']}",
                    f"  Summa: {format_amount(item['amount'])}",
                    f"  Dalil: {_proof_text(item)}",
                ]
            )
        lines.append("")

    if len(transactions) > len(shown_transactions):
        lines.append(
            f"Ko'rsatilgani: oxirgi {len(shown_transactions)} ta tranzaksiya. "
            f"Jami: {len(transactions)} ta."
        )

    return "\n".join(lines).strip()


async def _send_stats(target: Message | CallbackQuery, user_id: int, group_id: int, page: int = 0) -> None:
    group = await queries.get_group(group_id)
    if not group:
        text = "⚠️ Bu guruh endi topilmadi. Iltimos, qayta urinib ko'ring."
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return

    stats = await queries.get_stats_for_user(group_id, user_id)
    member_entries = await queries.get_stats_member_entries(group_id, user_id)
    for entry in member_entries:
        entry["button_text"] = _member_button_text(entry)
    stats["member_entries"] = member_entries

    keyboard = menus.stats_members_keyboard(member_entries, group_id, page=page)
    text = _stats_text(group["name"], stats)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=keyboard)
        await target.answer()
        return

    await target.answer(text, reply_markup=keyboard)


async def _send_pair_history(
    target: Message | CallbackQuery,
    user_id: int,
    group_id: int,
    member_id: int,
    period: str,
) -> None:
    group = await queries.get_group(group_id)
    if not group:
        text = "⚠️ Bu guruh endi topilmadi. Iltimos, qayta urinib ko'ring."
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return

    period_label, start_local, end_local = get_period_bounds(period)
    start_utc = to_utc(start_local)
    end_utc = to_utc(end_local)
    history = await queries.get_pair_transaction_history(
        group_id=group_id,
        user_id=user_id,
        other_id=member_id,
        start_utc=start_utc,
        end_utc=end_utc,
    )
    if not history:
        text = "⚠️ Bu a'zo endi topilmadi."
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return

    start_text = format_timestamp(start_utc) if start_utc else "Boshlanishidan"
    end_text = format_timestamp(end_utc) if end_utc else "Hozirgacha"
    text = _pair_history_text(
        group_name=group["name"],
        member_name=history["member_name"],
        period_label=period_label,
        start_text=start_text,
        end_text=end_text,
        history=history,
    )
    keyboard = menus.stats_pair_period_keyboard(group_id, member_id, period)

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


@router.callback_query(F.data.startswith("stats_members_page:"), flags={"member_required": True})
async def stats_members_page_callback(callback: CallbackQuery) -> None:
    _, group_id_text, page_text = callback.data.split(":")
    await _send_stats(callback, callback.from_user.id, int(group_id_text), page=int(page_text))


@router.callback_query(F.data.startswith("stats_member:"), flags={"member_required": True})
async def stats_member_callback(callback: CallbackQuery) -> None:
    _, group_id_text, member_id_text = callback.data.split(":")
    await _send_pair_history(
        callback,
        callback.from_user.id,
        int(group_id_text),
        int(member_id_text),
        period="month",
    )


@router.callback_query(F.data.startswith("stats_pair:"), flags={"member_required": True})
async def stats_pair_callback(callback: CallbackQuery) -> None:
    _, group_id_text, member_id_text, period = callback.data.split(":")
    await _send_pair_history(
        callback,
        callback.from_user.id,
        int(group_id_text),
        int(member_id_text),
        period=period,
    )


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
