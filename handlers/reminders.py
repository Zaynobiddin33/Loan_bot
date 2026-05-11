from __future__ import annotations

from contextlib import suppress
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import queries
from keyboards import menus
from states import ReminderStates
from utils.formatters import format_amount


router = Router(name="reminders")

CUSTOM_TEXT_MAX_LENGTH = 800


def _default_reminder_text(
    *,
    lender_name: str,
    debtor_name: str,
    group_name: str,
    amount: float,
    lender_card: str | None,
) -> str:
    lines = [
        "🔔 Eslatma",
        "",
        f"Salom, {debtor_name}!",
        f"{group_name} guruhida {lender_name} ga {format_amount(amount)} qarzdorsiz.",
        "Imkoniyat bo'lganda to'lab qo'ysangiz juda yaxshi bo'lardi 🙏",
    ]
    if lender_card:
        lines.extend(["", f"💳 Karta: {lender_card}"])
    return "\n".join(lines)


def _custom_reminder_text(
    *,
    lender_name: str,
    debtor_name: str,
    group_name: str,
    amount: float,
    lender_card: str | None,
    custom_text: str,
) -> str:
    lines = [
        f"🔔 Eslatma — {lender_name} dan",
        f"Guruh: {group_name}",
        f"Hozirgi qarz: {format_amount(amount)}",
        "",
        custom_text,
    ]
    if lender_card:
        lines.extend(["", f"💳 Karta: {lender_card}"])
    return "\n".join(lines)


def _build_reminder_text(
    *,
    message_type: str,
    lender_name: str,
    debtor: dict[str, Any],
    group_name: str,
    lender_card: str | None,
    custom_text: str | None,
) -> str:
    if message_type == "custom" and custom_text:
        return _custom_reminder_text(
            lender_name=lender_name,
            debtor_name=debtor["name"],
            group_name=group_name,
            amount=debtor["amount"],
            lender_card=lender_card,
            custom_text=custom_text,
        )
    return _default_reminder_text(
        lender_name=lender_name,
        debtor_name=debtor["name"],
        group_name=group_name,
        amount=debtor["amount"],
        lender_card=lender_card,
    )


async def _show_debtor_selection(
    target: Message | CallbackQuery,
    state: FSMContext,
    user_id: int,
    group_id: int,
    page: int = 0,
) -> None:
    group = await queries.get_group(group_id)
    if not group:
        text = "⚠️ Ushbu guruh topilmadi."
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return

    balances = await queries.get_user_net_balances(group_id, user_id)
    debtors = balances["people_owe_you"]

    if not debtors:
        text = f"✅ {group['name']} guruhida hozir hech kim sizga qarzdor emas."
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=menus.back_to_menu_inline())
            await target.answer()
        else:
            await target.answer(text)
        return

    data = await state.get_data()
    valid_ids = {debtor["telegram_id"] for debtor in debtors}
    selected_ids = set(data.get("selected_debtor_ids", [])) & valid_ids
    ordered_selected = [debtor["telegram_id"] for debtor in debtors if debtor["telegram_id"] in selected_ids]

    await state.set_state(ReminderStates.select_debtors)
    await state.update_data(
        group_id=group_id,
        selected_debtor_ids=ordered_selected,
    )

    text_lines = [
        f"🔔 {group['name']} guruhida kimga eslatma yuborasiz?",
        "",
        "Bir yoki bir nechta qarzdorni tanlang:",
    ]
    if selected_ids:
        selected_names = [debtor["name"] for debtor in debtors if debtor["telegram_id"] in selected_ids]
        text_lines.extend(["", f"Tanlanganlar: {', '.join(selected_names)}"])

    markup = menus.reminder_debtor_selection_keyboard(debtors, selected_ids, page)

    if isinstance(target, CallbackQuery):
        with suppress(TelegramBadRequest):
            await target.message.edit_text("\n".join(text_lines), reply_markup=markup)
        await target.answer()
        return

    await target.answer("\n".join(text_lines), reply_markup=markup)


async def _show_message_type_prompt(
    target: Message | CallbackQuery,
    state: FSMContext,
) -> None:
    await state.set_state(ReminderStates.select_message_type)
    text = (
        "📨 Qaysi xabarni yuborasiz?\n\n"
        "• 📝 Standart xabar — bot avtomatik tayyorlangan eslatma yuboradi.\n"
        "• ✏️ O'z matnim — o'zingiz yozgan matnni yuborasiz (qarz konteksti avtomatik qo'shiladi)."
    )
    markup = menus.reminder_message_type_keyboard()

    if isinstance(target, CallbackQuery):
        with suppress(TelegramBadRequest):
            await target.message.edit_text(text, reply_markup=markup)
        await target.answer()
        return

    await target.answer(text, reply_markup=markup)


async def _show_confirmation(
    target: Message | CallbackQuery,
    state: FSMContext,
    user_id: int,
    fallback_username: str | None,
) -> None:
    data = await state.get_data()
    group_id = data["group_id"]
    message_type = data["message_type"]
    custom_text = data.get("custom_text")
    selected_ids: list[int] = data.get("selected_debtor_ids", [])

    group = await queries.get_group(group_id)
    balances = await queries.get_user_net_balances(group_id, user_id)
    debtors_by_id = {debtor["telegram_id"]: debtor for debtor in balances["people_owe_you"]}
    selected_debtors = [debtors_by_id[debtor_id] for debtor_id in selected_ids if debtor_id in debtors_by_id]

    if not group or not selected_debtors:
        text = "⚠️ Tanlangan qarzdorlardan biri ham endi topilmadi. Iltimos, qaytadan boshlang."
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=menus.back_to_menu_inline())
            await target.answer()
        else:
            await target.answer(text, reply_markup=menus.back_to_menu_inline())
        await state.clear()
        return

    lender_name = await queries.get_group_member_display_name(
        group_id,
        user_id,
        fallback_username=fallback_username,
    )
    lender_card = await queries.get_saved_card(user_id)

    preview = _build_reminder_text(
        message_type=message_type,
        lender_name=lender_name,
        debtor=selected_debtors[0],
        group_name=group["name"],
        lender_card=lender_card,
        custom_text=custom_text,
    )

    recipient_lines = [f"• {debtor['name']} — {format_amount(debtor['amount'])}" for debtor in selected_debtors]
    text = (
        "📨 Eslatma tafsiloti\n\n"
        f"Guruh: {group['name']}\n"
        f"Qabul qiluvchilar ({len(selected_debtors)}):\n"
        f"{chr(10).join(recipient_lines)}\n\n"
        f"--- Birinchi qabul qiluvchi uchun namuna ---\n{preview}"
    )

    await state.set_state(ReminderStates.confirm_send)

    markup = menus.reminder_confirm_keyboard()
    if isinstance(target, CallbackQuery):
        with suppress(TelegramBadRequest):
            await target.message.edit_text(text, reply_markup=markup)
        await target.answer()
        return

    await target.answer(text, reply_markup=markup)


@router.message(F.text == "🔔 Eslatma yuborish", flags={"member_required": True})
async def reminder_entry(
    message: Message,
    state: FSMContext,
    user_groups: list[dict[str, Any]],
) -> None:
    await state.clear()
    if len(user_groups) == 1:
        await _show_debtor_selection(message, state, message.from_user.id, user_groups[0]["id"])
        return

    await state.set_state(ReminderStates.select_group)
    await message.answer(
        "🔔 Eslatma yuborish uchun guruhni tanlang:",
        reply_markup=menus.group_selection_keyboard(user_groups, "reminder_group"),
    )


@router.callback_query(F.data.startswith("reminder_group:"), flags={"member_required": True})
async def reminder_group_callback(callback: CallbackQuery, state: FSMContext) -> None:
    group_id = int(callback.data.split(":")[1])
    await _show_debtor_selection(callback, state, callback.from_user.id, group_id)


@router.callback_query(F.data.startswith("reminder_toggle_all:"), ReminderStates.select_debtors, flags={"member_required": True})
async def reminder_toggle_all_callback(callback: CallbackQuery, state: FSMContext) -> None:
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    group_id = data["group_id"]
    balances = await queries.get_user_net_balances(group_id, callback.from_user.id)
    debtors = balances["people_owe_you"]
    debtor_ids = {debtor["telegram_id"] for debtor in debtors}
    current_selected = set(data.get("selected_debtor_ids", []))

    if current_selected == debtor_ids:
        ordered_selected: list[int] = []
    else:
        ordered_selected = [debtor["telegram_id"] for debtor in debtors]

    await state.update_data(selected_debtor_ids=ordered_selected)
    await _show_debtor_selection(callback, state, callback.from_user.id, group_id, page=page)


@router.callback_query(F.data.startswith("reminder_toggle:"), ReminderStates.select_debtors, flags={"member_required": True})
async def reminder_toggle_callback(callback: CallbackQuery, state: FSMContext) -> None:
    _, debtor_id_text, page_text = callback.data.split(":")
    debtor_id = int(debtor_id_text)
    page = int(page_text)

    data = await state.get_data()
    group_id = data["group_id"]
    balances = await queries.get_user_net_balances(group_id, callback.from_user.id)
    debtors = balances["people_owe_you"]

    selected_ids = set(data.get("selected_debtor_ids", []))
    if debtor_id in selected_ids:
        selected_ids.remove(debtor_id)
    else:
        selected_ids.add(debtor_id)

    ordered_selected = [debtor["telegram_id"] for debtor in debtors if debtor["telegram_id"] in selected_ids]
    await state.update_data(selected_debtor_ids=ordered_selected)
    await _show_debtor_selection(callback, state, callback.from_user.id, group_id, page=page)


@router.callback_query(F.data.startswith("reminder_page:"), ReminderStates.select_debtors, flags={"member_required": True})
async def reminder_page_callback(callback: CallbackQuery, state: FSMContext) -> None:
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    await _show_debtor_selection(callback, state, callback.from_user.id, data["group_id"], page=page)


@router.callback_query(F.data == "reminder_continue", ReminderStates.select_debtors, flags={"member_required": True})
async def reminder_continue_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("selected_debtor_ids"):
        await callback.answer("Avvalo kamida bitta qarzdorni tanlang.", show_alert=True)
        return

    await _show_message_type_prompt(callback, state)


@router.callback_query(F.data.startswith("reminder_msg:"), ReminderStates.select_message_type, flags={"member_required": True})
async def reminder_msg_callback(callback: CallbackQuery, state: FSMContext) -> None:
    choice = callback.data.split(":")[1]
    if choice not in {"default", "custom"}:
        await callback.answer()
        return

    await state.update_data(message_type=choice, custom_text=None)

    if choice == "default":
        await _show_confirmation(callback, state, callback.from_user.id, callback.from_user.username)
        return

    await state.set_state(ReminderStates.enter_custom_text)
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        (
            "✏️ Yubormoqchi bo'lgan matnni yozing.\n\n"
            f"Maksimal {CUSTOM_TEXT_MAX_LENGTH} ta belgi. Har bir qabul qiluvchi uchun guruh nomi, "
            "qarz summasi va kartangiz avtomatik qo'shiladi."
        ),
        reply_markup=menus.cancel_reply_keyboard(),
    )
    await callback.answer()


@router.message(ReminderStates.enter_custom_text)
async def reminder_custom_text_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("⚠️ Matn bo'sh bo'lmasligi kerak. Iltimos, yozing yoki ❌ Bekor qilishni bosing.")
        return
    if len(text) > CUSTOM_TEXT_MAX_LENGTH:
        await message.answer(
            f"⚠️ Matn juda uzun ({len(text)} belgi). Iltimos, {CUSTOM_TEXT_MAX_LENGTH} belgidan oshmasligiga e'tibor bering."
        )
        return

    await state.update_data(custom_text=text)
    await _show_confirmation(message, state, message.from_user.id, message.from_user.username)


@router.callback_query(F.data == "reminder_send", ReminderStates.confirm_send, flags={"member_required": True})
async def reminder_send_callback(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    group_id = data["group_id"]
    message_type = data["message_type"]
    custom_text = data.get("custom_text")
    selected_ids: list[int] = data.get("selected_debtor_ids", [])

    group = await queries.get_group(group_id)
    balances = await queries.get_user_net_balances(group_id, callback.from_user.id)
    debtors_by_id = {debtor["telegram_id"]: debtor for debtor in balances["people_owe_you"]}
    selected_debtors = [debtors_by_id[debtor_id] for debtor_id in selected_ids if debtor_id in debtors_by_id]

    if not group or not selected_debtors:
        await state.clear()
        await callback.message.edit_text(
            "⚠️ Tanlangan qarzdorlardan biri ham endi topilmadi. Iltimos, qaytadan boshlang.",
            reply_markup=menus.back_to_menu_inline(),
        )
        await callback.answer()
        return

    lender_name = await queries.get_group_member_display_name(
        group_id,
        callback.from_user.id,
        fallback_username=callback.from_user.username,
    )
    lender_card = await queries.get_saved_card(callback.from_user.id)

    await callback.message.edit_text("⏳ Eslatmalar yuborilmoqda...")

    delivered: list[str] = []
    failed: list[str] = []

    for debtor in selected_debtors:
        text = _build_reminder_text(
            message_type=message_type,
            lender_name=lender_name,
            debtor=debtor,
            group_name=group["name"],
            lender_card=lender_card,
            custom_text=custom_text,
        )
        try:
            await bot.send_message(chat_id=debtor["telegram_id"], text=text)
            delivered.append(debtor["name"])
        except TelegramForbiddenError:
            failed.append(debtor["name"])
        except TelegramAPIError:
            failed.append(debtor["name"])

    await state.clear()

    summary_lines = [
        f"✅ Eslatma yuborildi: {len(delivered)}/{len(selected_debtors)}",
    ]
    if delivered:
        summary_lines.append("")
        summary_lines.append("Yetkazilganlar:")
        summary_lines.extend(f"• {name}" for name in delivered)
    if failed:
        summary_lines.append("")
        summary_lines.append("Yetkazilmaganlar (botni hali ishga tushirmagan yoki bloklagan bo'lishi mumkin):")
        summary_lines.extend(f"• {name}" for name in failed)

    await callback.message.edit_text(
        "\n".join(summary_lines),
        reply_markup=menus.back_to_menu_inline(),
    )
    await callback.answer()
