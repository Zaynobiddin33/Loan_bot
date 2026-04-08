from __future__ import annotations

from contextlib import suppress
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import queries
from keyboards import menus
from states import LoanStates
from utils.formatters import format_amount, parse_amount


router = Router(name="loans")


def _participant_name(member: dict[str, Any], user_id: int) -> str:
    if member["telegram_id"] == user_id:
        return f"{member['display_name']} (Siz)"
    return member["display_name"]


def _participant_prompt(
    group_name: str,
    members: list[dict[str, Any]],
    selected_ids: set[int],
    user_id: int,
) -> str:
    lines = [
        f"💸 {group_name} guruhida qarz berish",
        "",
        "Ushbu summaga kirgan odamlarni tanlang:",
        "O'zingizni ham tanlashingiz mumkin. Sizning ulushingiz qarz sifatida yozilmaydi.",
    ]

    if selected_ids:
        selected_names = [_participant_name(member, user_id) for member in members if member["telegram_id"] in selected_ids]
        lines.append("")
        lines.append(f"Tanlanganlar: {', '.join(selected_names)}")

    return "\n".join(lines)


def _loan_amount_preview(distribution: dict[str, Any], total_amount: float) -> str:
    participant_shares = [item["amount"] for item in distribution["participant_shares"]]
    borrower_shares = [item["amount"] for item in distribution["borrower_allocations"]]
    lender_share = distribution["lender_share"]

    if lender_share > 0:
        if not borrower_shares:
            return (
                f"Sizning ulushingiz: {format_amount(lender_share)}. "
                "Boshqa a'zo tanlanmagan, shuning uchun qarz yozilmaydi."
            )

        unique_borrower_shares = sorted({format_amount(share) for share in borrower_shares})
        if len(unique_borrower_shares) == 1:
            return (
                f"Sizning ulushingiz ayiriladi: {format_amount(lender_share)}. "
                f"Qolgan {format_amount(distribution['borrower_total'])} "
                f"{len(borrower_shares)} kishiga bo'linadi: har biri {unique_borrower_shares[0]}."
            )

        return (
            f"Sizning ulushingiz ayiriladi: {format_amount(lender_share)}. "
            f"Qolgan {format_amount(distribution['borrower_total'])} taqsimlandi; "
            f"yaxlitlash tufayli birinchi kishining ulushi {format_amount(borrower_shares[0])}, "
            f"qolganlariniki {format_amount(borrower_shares[-1])}."
        )

    if len(participant_shares) == 1:
        return f"Qarz summasi: {format_amount(total_amount)}"

    unique_shares = sorted({format_amount(share) for share in participant_shares})
    if len(unique_shares) == 1:
        return (
            f"Har bir kishi qarzdor bo'ladi: {unique_shares[0]} "
            f"(umumiy {format_amount(total_amount)} {len(participant_shares)} kishiga bo'linadi)"
        )

    return (
        f"Aksariyat uchun ulush: {format_amount(participant_shares[-1])}. "
        f"Yaxlitlash tufayli birinchi qarz oluvchining ulushi: {format_amount(participant_shares[0])}."
    )


async def _open_borrower_selection(
    target: Message | CallbackQuery,
    state: FSMContext,
    user_id: int,
    group_id: int,
    page: int = 0,
) -> None:
    group = await queries.get_group(group_id)
    members = await queries.get_group_members(group_id)

    if not group:
        text = "⚠️ Ushbu guruh topilmadi."
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.answer(text)
        return

    if not any(member["telegram_id"] != user_id for member in members):
        text = "⚠️ Qarzni berishdan oldin guruhga ko'proq a'zolar qo'shing."
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=menus.back_to_menu_inline())
            await target.answer()
        else:
            await target.answer(text)
        return

    for member in members:
        member["selection_name"] = _participant_name(member, user_id)

    data = await state.get_data()
    valid_member_ids = {member["telegram_id"] for member in members}
    selected_ids = set(data.get("selected_participant_ids", data.get("selected_borrower_ids", []))) & valid_member_ids
    ordered_selected_ids = [member["telegram_id"] for member in members if member["telegram_id"] in selected_ids]
    await state.set_state(LoanStates.select_borrowers)
    await state.update_data(group_id=group_id, selected_participant_ids=ordered_selected_ids)

    text = _participant_prompt(group["name"], members, selected_ids, user_id)
    markup = menus.borrower_selection_keyboard(members, selected_ids, page)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup)
        await target.answer()
        return

    await target.answer(text, reply_markup=markup)


@router.message(F.text == "💸 Qarzni berish", flags={"member_required": True})
async def give_loan_entry(
    message: Message,
    state: FSMContext,
    user_groups: list[dict[str, Any]],
) -> None:
    await state.clear()
    if len(user_groups) == 1:
        await _open_borrower_selection(message, state, message.from_user.id, user_groups[0]["id"])
        return

    await state.set_state(LoanStates.select_group)
    await message.answer(
        "💸 Guruhni tanlang:",
        reply_markup=menus.group_selection_keyboard(user_groups, "loan_group"),
    )


@router.callback_query(F.data.startswith("loan_group:"), flags={"member_required": True})
async def loan_group_callback(callback: CallbackQuery, state: FSMContext) -> None:
    group_id = int(callback.data.split(":")[1])
    await _open_borrower_selection(callback, state, callback.from_user.id, group_id)


@router.callback_query(F.data.startswith("loan_toggle_all:"), LoanStates.select_borrowers, flags={"member_required": True})
async def loan_toggle_all_callback(callback: CallbackQuery, state: FSMContext) -> None:
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    group_id = data["group_id"]
    members = await queries.get_group_members(group_id)
    member_ids = {member["telegram_id"] for member in members}
    current_selected = set(data.get("selected_participant_ids", data.get("selected_borrower_ids", [])))

    if current_selected == member_ids:
        ordered_selected_ids: list[int] = []
    else:
        ordered_selected_ids = [member["telegram_id"] for member in members]

    await state.update_data(selected_participant_ids=ordered_selected_ids)
    await _open_borrower_selection(callback, state, callback.from_user.id, group_id, page=page)


@router.callback_query(
    F.data.startswith("loan_toggle_member:"),
    LoanStates.select_borrowers,
    flags={"member_required": True},
)
async def loan_toggle_member_callback(callback: CallbackQuery, state: FSMContext) -> None:
    _, member_id_text, page_text = callback.data.split(":")
    member_id = int(member_id_text)
    page = int(page_text)

    data = await state.get_data()
    group_id = data["group_id"]
    members = await queries.get_group_members(group_id)
    selected_ids = set(data.get("selected_participant_ids", data.get("selected_borrower_ids", [])))
    if member_id in selected_ids:
        selected_ids.remove(member_id)
    else:
        selected_ids.add(member_id)

    ordered_selected_ids = [member["telegram_id"] for member in members if member["telegram_id"] in selected_ids]
    await state.update_data(selected_participant_ids=ordered_selected_ids)
    await _open_borrower_selection(callback, state, callback.from_user.id, group_id, page=page)


@router.callback_query(F.data.startswith("loan_page:"), LoanStates.select_borrowers, flags={"member_required": True})
async def loan_page_callback(callback: CallbackQuery, state: FSMContext) -> None:
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    await _open_borrower_selection(callback, state, callback.from_user.id, data["group_id"], page=page)


@router.callback_query(F.data == "loan_continue", LoanStates.select_borrowers, flags={"member_required": True})
async def loan_continue_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected_ids = data.get("selected_participant_ids", data.get("selected_borrower_ids", []))
    if not selected_ids:
        await callback.answer("Avvalo kamida bitta qatnashchini tanlang.", show_alert=True)
        return

    if not any(participant_id != callback.from_user.id for participant_id in selected_ids):
        await callback.answer(
            "Kamida bitta boshqa a'zoni tanlang. O'zingizni faqat ulush uchun qo'shishingiz mumkin.",
            show_alert=True,
        )
        return

    await state.set_state(LoanStates.enter_amount)
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Umumiy qarz miqdorini kiriting (masalan, 150000):",
        reply_markup=menus.cancel_reply_keyboard(),
    )
    await callback.answer()


@router.message(LoanStates.enter_amount)
async def loan_amount_handler(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message.text or "")
    if amount is None:
        await message.answer(
            "⚠️ Bu haqiqiy summa kabi ko'rinmaydi. Iltimos, 5000 yoki 12500 kabi raqam kiriting."
        )
        return

    data = await state.get_data()
    participant_ids = data.get("selected_participant_ids", data.get("selected_borrower_ids", []))
    if not participant_ids:
        await state.clear()
        await message.answer("⚠️ Qatnashchilar ro'yxati hozir bo'sh. Iltimos, qaytadan boshlang.")
        return

    distribution = queries.build_loan_distribution(amount, participant_ids, message.from_user.id)
    if not distribution["borrower_allocations"]:
        await state.clear()
        await message.answer(
            "⚠️ Faqat o'zingiz tanlangansiz. Iltimos, qaytadan boshlang va kamida bitta boshqa a'zoni tanlang."
        )
        return

    await state.update_data(total_amount=amount, loan_distribution=distribution)
    await state.set_state(LoanStates.enter_comment)

    preview = _loan_amount_preview(distribution, amount)
    await message.answer(
        f"{preview}\n\nUshbu qarz uchun izoh kiriting (masalan, 'Restorandagi ovqat', 'Taksi haqi'):",
        reply_markup=menus.cancel_reply_keyboard(),
    )


@router.message(LoanStates.enter_comment)
async def loan_comment_handler(message: Message, state: FSMContext) -> None:
    comment = (message.text or "").strip()
    if not comment:
        await message.answer("⚠️ Har bir qarz uchun izoh kerak. Iltimos, yozing yoki ❌ Bekor qilishni bosing.")
        return

    data = await state.get_data()
    group = await queries.get_group(data["group_id"])
    members = await queries.get_group_members(data["group_id"])
    member_map = {member["telegram_id"]: member for member in members}
    participant_ids = data.get("selected_participant_ids", data.get("selected_borrower_ids", []))
    distribution = data.get("loan_distribution") or queries.build_loan_distribution(
        data["total_amount"],
        participant_ids,
        message.from_user.id,
    )
    share_map = {item["participant_id"]: item["amount"] for item in distribution["participant_shares"]}

    participant_lines = []
    participant_names = []
    for participant_id in participant_ids:
        member = member_map.get(participant_id)
        if not member:
            continue

        participant_name = _participant_name(member, message.from_user.id)
        share = share_map[participant_id]
        participant_names.append(participant_name)

        if participant_id == message.from_user.id:
            participant_lines.append(
                f"• {participant_name}: {format_amount(share)} (sizning ulushingiz, qarz yozilmaydi)"
            )
        else:
            participant_lines.append(f"• {participant_name}: {format_amount(share)}")

    await state.update_data(comment=comment)
    await state.set_state(LoanStates.confirm_loan)
    group_name = group["name"] if group else "Noma'lum guruh"

    text = (
        "💸 Qarz tafsiloti\n\n"
        "Kimdan: Siz\n"
        f"Guruh: {group_name}\n"
        f"Qatnashchilar: {', '.join(participant_names)}\n"
        f"Taqsimot:\n{chr(10).join(participant_lines)}\n"
        f"Jami: {format_amount(data['total_amount'])}\n"
        f"Izoh: {comment}"
    )
    await message.answer(text, reply_markup=menus.confirmation_keyboard("loan_confirm"))


@router.callback_query(F.data == "loan_confirm", LoanStates.confirm_loan, flags={"member_required": True})
async def loan_confirm_callback(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    group_id = data["group_id"]
    participant_ids = data.get("selected_participant_ids", data.get("selected_borrower_ids", []))
    total_amount = data["total_amount"]
    comment = data["comment"]
    distribution = data.get("loan_distribution") or queries.build_loan_distribution(
        total_amount,
        participant_ids,
        callback.from_user.id,
    )

    members = await queries.get_group_members(group_id)
    current_member_ids = {member["telegram_id"] for member in members}
    if not participant_ids or not set(participant_ids).issubset(current_member_ids):
        await state.clear()
        await callback.message.edit_text(
            "⚠️ Tanlangan qatnashchilardan biri yoki bir nechtasi guruhda yo'q. Iltimos, qaytadan boshlang.",
            reply_markup=menus.back_to_menu_inline(),
        )
        await callback.answer()
        return

    if not distribution["borrower_allocations"]:
        await state.clear()
        await callback.message.edit_text(
            "⚠️ Faqat o'zingiz tanlangansiz. Iltimos, qaytadan boshlang va kamida bitta boshqa a'zoni tanlang.",
            reply_markup=menus.back_to_menu_inline(),
        )
        await callback.answer()
        return

    await callback.message.edit_text("⏳ Iltimos kuting...")
    loans = await queries.create_loans(
        group_id=group_id,
        lender_id=callback.from_user.id,
        participant_ids=participant_ids,
        total_amount=total_amount,
        comment=comment,
    )
    await state.clear()

    lender_name = await queries.get_group_member_display_name(
        group_id,
        callback.from_user.id,
        fallback_username=callback.from_user.username,
    )
    member_map = {member["telegram_id"]: member for member in members}
    for loan in loans:
        borrower = member_map.get(loan["borrower_id"])
        if not borrower:
            continue
        try:
            await bot.send_message(
                chat_id=loan["borrower_id"],
                text=(
                    "⚠️ Yangi qarz yozildi!\n"
                    f"Kimdan: {lender_name}\n"
                    f"Summa: {format_amount(loan['amount'])}\n"
                    f"Izoh: {comment}\n"
                    "Bu qarzni yopish uchun 'Qarzni to'lash'ni ishlating."
                ),
            )
        except TelegramForbiddenError:
            pass
        except TelegramAPIError:
            pass

    await callback.message.edit_text(
        (
            f"✅ {len(loans)} qarzdorga qarz yozildi."
            + (
                f"\nSizning ulushingiz: {format_amount(distribution['lender_share'])}."
                if distribution["lender_share"] > 0
                else ""
            )
        ),
        reply_markup=menus.back_to_menu_inline(),
    )

    await callback.answer()
