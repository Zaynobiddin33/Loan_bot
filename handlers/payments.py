from __future__ import annotations

from contextlib import suppress
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import queries
from keyboards import menus
from states import PaymentStates
from utils.formatters import format_amount, parse_amount


router = Router(name="payments")


async def _show_creditor_selection(
    target: Message | CallbackQuery,
    state: FSMContext,
    user_id: int,
    group_id: int,
) -> None:
    group = await queries.get_group(group_id)
    creditors = await queries.get_creditors_for_user(group_id, user_id)

    if not group:
        text = "⚠️ Ushbu guruh topilmadi."
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return

    if not creditors:
        text = f"✅ Siz hozirda {group['name']} guruhida hech kimga qarzdor emassiz."
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=menus.back_to_menu_inline())
            await target.answer()
        else:
            await target.answer(text)
        return

    await state.set_state(PaymentStates.select_creditor)
    await state.update_data(group_id=group_id)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(
            f"💰 {group['name']} guruhida to'lashni istagan shaxsni tanlang:",
            reply_markup=menus.creditor_keyboard(creditors),
        )
        await target.answer()
        return

    await target.answer(
        f"💰 {group['name']} guruhida to'lashni istagan shaxsni tanlang:",
        reply_markup=menus.creditor_keyboard(creditors),
    )


@router.message(F.text == "💰 Qarzni to'lash", flags={"member_required": True})
async def pay_debt_entry(
    message: Message,
    state: FSMContext,
    user_groups: list[dict[str, Any]],
) -> None:
    await state.clear()
    if len(user_groups) == 1:
        await _show_creditor_selection(message, state, message.from_user.id, user_groups[0]["id"])
        return

    await state.set_state(PaymentStates.select_group)
    await message.answer(
        "💰 Guruhni tanlang:",
        reply_markup=menus.group_selection_keyboard(user_groups, "payment_group"),
    )


@router.callback_query(F.data.startswith("payment_group:"), flags={"member_required": True})
async def payment_group_callback(callback: CallbackQuery, state: FSMContext) -> None:
    group_id = int(callback.data.split(":")[1])
    await _show_creditor_selection(callback, state, callback.from_user.id, group_id)


@router.callback_query(F.data.startswith("payment_creditor:"), PaymentStates.select_creditor, flags={"member_required": True})
async def payment_creditor_callback(callback: CallbackQuery, state: FSMContext) -> None:
    creditor_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    group_id = data["group_id"]

    net = await queries.get_net_balance(group_id, callback.from_user.id, creditor_id)
    if net["amount"] <= 0 or net["debtor_id"] != callback.from_user.id:
        await callback.answer("⚠️ Bu qarz allaqachon yopilgan.", show_alert=True)
        await _show_creditor_selection(callback, state, callback.from_user.id, group_id)
        return

    creditor = await queries.get_group_member(group_id, creditor_id)
    if not creditor:
        await callback.answer("⚠️ Ushbu shaxs topilmadi.", show_alert=True)
        return

    await state.set_state(PaymentStates.enter_amount)
    await state.update_data(
        creditor_id=creditor_id,
        creditor_name=creditor["display_name"],
        max_amount=net["amount"],
    )

    card_line = f"\n💳 Karta: {creditor['card_number']}" if creditor.get("card_number") else ""
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        (
            f"Hozirgi sof qarz {creditor['display_name']} ga: {format_amount(net['amount'])}"
            f"{card_line}\n\nQancha to'lamoqchisiz? (maks: {format_amount(net['amount'])})"
        ),
        reply_markup=menus.cancel_reply_keyboard(),
    )
    await callback.answer()


@router.message(PaymentStates.enter_amount)
async def payment_amount_handler(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message.text or "")
    if amount is None:
        await message.answer(
            "⚠️ Bu haqiqiy summa kabi ko'rinmaydi. Iltimos, 5000 yoki 12500 kabi raqam kiriting."
        )
        return

    data = await state.get_data()
    max_amount = float(data["max_amount"])
    if amount > max_amount:
        await message.answer(
            f"⚠️ Bu hozirgi qarzingizdan katta. Iltimos, maksimal {format_amount(max_amount)} ni kiriting."
        )
        return

    await state.update_data(payment_amount=amount)
    await state.set_state(PaymentStates.upload_proof)
    await message.answer(
        "To'lov dalilini yuboring — skrinshot yoki matnli eslatma:",
        reply_markup=menus.cancel_reply_keyboard(),
    )


@router.message(PaymentStates.upload_proof)
async def payment_proof_handler(message: Message, state: FSMContext) -> None:
    if message.photo:
        proof_type = "image"
        proof_content = message.photo[-1].file_id
        note = (message.caption or "").strip() or None
        preview = "Skrinshot biriktirildi"
        if note:
            preview = f"{preview} ({note})"
    elif message.text:
        proof_type = "text"
        proof_content = message.text.strip()
        note = None
        preview = f"Matnli eslatma: {proof_content}"
    else:
        await message.answer("⚠️ Iltimos, to'lov dalili sifatida skrinshot yoki matnli eslatma yuboring.")
        return

    await state.update_data(
        proof_type=proof_type,
        proof_content=proof_content,
        proof_note=note,
        proof_preview=preview,
    )
    await state.set_state(PaymentStates.confirm_payment)

    data = await state.get_data()
    await message.answer(
        "💰 To'lov tafsiloti\n\n"
        f"Kimga: {data['creditor_name']}\n"
        f"Summa: {format_amount(data['payment_amount'])}\n"
        f"Dalil: {preview}",
        reply_markup=menus.confirmation_keyboard("payment_confirm"),
    )


@router.callback_query(F.data == "payment_confirm", PaymentStates.confirm_payment, flags={"member_required": True})
async def payment_confirm_callback(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    group_id = data["group_id"]
    creditor_id = data["creditor_id"]
    payment_amount = float(data["payment_amount"])

    current_net = await queries.get_net_balance(group_id, callback.from_user.id, creditor_id)
    if current_net["amount"] <= 0 or current_net["debtor_id"] != callback.from_user.id:
        await state.clear()
        await callback.message.edit_text(
            "⚠️ Bu qarz allaqachon yopilgan. Agar kerak bo'lsa, qaytadan boshlang.",
            reply_markup=menus.back_to_menu_inline(),
        )
        await callback.answer()
        return

    if payment_amount > current_net["amount"]:
        await state.clear()
        await callback.message.edit_text(
            "⚠️ Bu to'lov hozirgi sof qarzdan katta. Iltimos, to'lov jarayonini qayta boshlang.",
            reply_markup=menus.back_to_menu_inline(),
        )
        await callback.answer()
        return

    await callback.message.edit_text("⏳ Iltimos kuting...")
    await queries.record_payment(
        group_id=group_id,
        payer_id=callback.from_user.id,
        creditor_id=creditor_id,
        amount=payment_amount,
        proof_type=data["proof_type"],
        proof_content=data["proof_content"],
        note=data.get("proof_note"),
    )
    await state.clear()

    payer_name = await queries.get_group_member_display_name(
        group_id,
        callback.from_user.id,
        fallback_username=callback.from_user.username,
    )
    text = (
        "💰 To'lov qabul qilindi!\n"
        f"Kimdan: {payer_name}\n"
        f"Summa: {format_amount(payment_amount)}\n"
        "✅ Bu avtomatik ravishda qayd etildi."
    )

    try:
        if data["proof_type"] == "image":
            caption = f"{text}\nDalil: skrinshot"
            if data.get("proof_note"):
                caption += f"\nEslatma: {data['proof_note']}"
            await bot.send_photo(
                chat_id=creditor_id,
                photo=data["proof_content"],
                caption=caption,
            )
        else:
            await bot.send_message(
                chat_id=creditor_id,
                text=f"{text}\nDalil: {data['proof_content']}",
            )
    except TelegramForbiddenError:
        pass
    except TelegramAPIError:
        pass

    await callback.message.edit_text(
        f"✅ {format_amount(payment_amount)} miqdordagi to'lov muvaffaqiyatli qayd etildi.",
        reply_markup=menus.back_to_menu_inline(),
    )
    await callback.answer()
