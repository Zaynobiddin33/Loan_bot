from __future__ import annotations

from contextlib import suppress
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import queries
from keyboards import menus
from states import AdminStates
from utils.formatters import format_amount, format_timestamp, telegram_user_name


router = Router(name="admin")


async def _ensure_admin(event: Message | CallbackQuery, user_id: int) -> bool:
    if await queries.is_admin(user_id):
        return True

    text = "⚠️ Faqat sozlangan adminlar bu paneldan foydalanishi mumkin."
    if isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)
    else:
        await event.answer(text)
    return False


def _extract_forwarded_user(message: Message) -> tuple[int, str | None, str] | None:
    origin = getattr(message, "forward_origin", None)
    sender_user = getattr(origin, "sender_user", None)
    if sender_user:
        return sender_user.id, sender_user.username, telegram_user_name(sender_user)

    legacy_user = getattr(message, "forward_from", None)
    if legacy_user:
        return legacy_user.id, legacy_user.username, telegram_user_name(legacy_user)

    return None


@router.message(F.text == "➕ Guruh yaratish")
async def create_group_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await _ensure_admin(message, message.from_user.id):
        return

    await state.set_state(AdminStates.waiting_group_name)
    await message.answer(
        "Yangi guruh nomini kiriting:",
        reply_markup=menus.cancel_reply_keyboard(),
    )


@router.message(AdminStates.waiting_group_name)
async def create_group_name_handler(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message, message.from_user.id):
        await state.clear()
        return

    group_name = (message.text or "").strip()
    if not group_name:
        await message.answer("⚠️ Iltimos, guruh nomini kiriting yoki ❌ Bekor qilish tugmasini bosing.")
        return

    processing = await message.answer("⏳ Iltimos kuting...")
    group = await queries.create_group(
        name=group_name,
        admin_id=message.from_user.id,
        admin_username=message.from_user.username,
        admin_full_name=telegram_user_name(message.from_user),
    )
    await state.clear()

    await processing.edit_text(
        f"✅ '{group['name']}' guruhi yaratildi! Endi 'A'zo qo'shish' orqali a'zolar qo'shing.",
        reply_markup=menus.back_to_menu_inline(),
    )


@router.message(F.text == "👤 A'zo qo'shish")
async def add_member_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await _ensure_admin(message, message.from_user.id):
        return

    groups = await queries.get_admin_groups(message.from_user.id)
    if not groups:
        await message.answer("⚠️ Sizda hali hech qanday guruh yo'q. Avvalo guruh yarating.")
        return

    await message.answer(
        "A'zo qo'shmoqchi bo'lgan guruhni tanlang:",
        reply_markup=menus.group_selection_keyboard(groups, "admin_add_group"),
    )


@router.callback_query(F.data.startswith("admin_add_group:"))
async def add_member_group_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(callback, callback.from_user.id):
        return

    group_id = int(callback.data.split(":")[1])
    group = await queries.get_group(group_id)
    if not group or group["admin_id"] != callback.from_user.id:
        await callback.answer("⚠️ Ushbu guruh mavjud emas.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_member_id)
    await state.update_data(group_id=group_id, group_name=group["name"])

    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Qo'shmoqchi bo'lgan foydalanuvchining xabarini yuboring, yoki ularning Telegram ID sini jo'nating.\n\n"
        "Agar ID yuborsangiz, keyingi bosqichda ismini ham kiritasiz.",
        reply_markup=menus.cancel_reply_keyboard(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_member_id)
async def add_member_handler(message: Message, state: FSMContext, bot: Bot) -> None:
    if not await _ensure_admin(message, message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    group_id = data["group_id"]
    group_name = data["group_name"]

    forwarded = _extract_forwarded_user(message)
    if forwarded:
        telegram_id, username, full_name = forwarded
        processing = await message.answer("⏳ Iltimos kuting...")
        created = await queries.add_member_to_group(
            group_id=group_id,
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
        )
        saved_member = await queries.get_group_member(group_id, telegram_id)
        await state.clear()

        admin_name = await queries.get_group_member_display_name(
            group_id,
            message.from_user.id,
            fallback_full_name=telegram_user_name(message.from_user),
            fallback_username=message.from_user.username,
        )
        member_message = f"🎉 Siz '{group_name}' guruhiga {admin_name} tomonidan qo'shildingiz!"

        try:
            await bot.send_message(chat_id=telegram_id, text=member_message)
        except TelegramForbiddenError:
            pass
        except TelegramAPIError:
            pass

        saved_name = saved_member["display_name"] if saved_member else full_name
        if created:
            text = f"✅ {saved_name} '{group_name}' guruhiga qo'shildi."
        else:
            text = f"✅ {saved_name} allaqachon '{group_name}' guruhida. Ularning ma'lumotlari yangilandi."

        await processing.edit_text(text, reply_markup=menus.back_to_menu_inline())
        return

    raw_text = (message.text or "").strip()
    if not raw_text.isdigit():
        await message.answer(
            "⚠️ Iltimos, foydalanuvchidan xabarni yo'nating yoki raqamli Telegram ID ni yuboring."
        )
        return

    telegram_id = int(raw_text)
    await state.set_state(AdminStates.waiting_member_name)
    await state.update_data(pending_member_id=telegram_id, pending_member_username=None)
    await message.answer(
        "Bu foydalanuvchi uchun ism kiriting:",
        reply_markup=menus.cancel_reply_keyboard(),
    )


@router.message(AdminStates.waiting_member_name)
async def add_member_name_handler(message: Message, state: FSMContext, bot: Bot) -> None:
    if not await _ensure_admin(message, message.from_user.id):
        await state.clear()
        return

    full_name = (message.text or "").strip()
    if not full_name:
        await message.answer("⚠️ Iltimos, ism kiriting yoki ❌ Bekor qilishni bosing.")
        return

    data = await state.get_data()
    group_id = data["group_id"]
    group_name = data["group_name"]
    telegram_id = data["pending_member_id"]
    username = data.get("pending_member_username")

    processing = await message.answer("⏳ Iltimos kuting...")
    created = await queries.add_member_to_group(
        group_id=group_id,
        telegram_id=telegram_id,
        username=username,
        full_name=full_name,
        prefer_new_name=True,
    )
    saved_member = await queries.get_group_member(group_id, telegram_id)
    await state.clear()

    admin_name = await queries.get_group_member_display_name(
        group_id,
        message.from_user.id,
        fallback_full_name=telegram_user_name(message.from_user),
        fallback_username=message.from_user.username,
    )
    member_message = f"🎉 Siz '{group_name}' guruhiga {admin_name} tomonidan qo'shildingiz!"

    try:
        await bot.send_message(chat_id=telegram_id, text=member_message)
    except TelegramForbiddenError:
        pass
    except TelegramAPIError:
        pass

    saved_name = saved_member["display_name"] if saved_member else full_name
    if created:
        text = f"✅ {saved_name} '{group_name}' guruhiga qo'shildi."
    else:
        text = f"✅ {saved_name} allaqachon '{group_name}' guruhida. Ma'lumotlari yangilandi."

    await processing.edit_text(text, reply_markup=menus.back_to_menu_inline())


@router.message(F.text == "🗑 A'zoni o'chirish")
async def remove_member_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await _ensure_admin(message, message.from_user.id):
        return

    groups = await queries.get_admin_groups(message.from_user.id)
    if not groups:
        await message.answer("⚠️ Sizda hali hech qanday guruh yo'q.")
        return

    await message.answer(
        "Qaysi guruhdan a'zo o'chirilishini tanlang:",
        reply_markup=menus.group_selection_keyboard(groups, "admin_remove_group"),
    )


async def _show_remove_members(callback: CallbackQuery, group_id: int, page: int = 0) -> None:
    group = await queries.get_group(group_id)
    if not group or group["admin_id"] != callback.from_user.id:
        await callback.answer("⚠️ Ushbu guruh mavjud emas.", show_alert=True)
        return

    members = await queries.get_group_members(group_id, exclude_user_id=callback.from_user.id)
    if not members:
        await callback.message.edit_text(
            "⚠️ Bu guruhda hozircha o'chiriladigan a'zo yo'q.",
            reply_markup=menus.back_to_menu_inline(),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"Quyidagi a'zolardan birini {group['name']} guruhidan o'chiring:",
        reply_markup=menus.remove_member_keyboard(group_id, members, page),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_remove_group:"))
async def remove_member_group_callback(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback, callback.from_user.id):
        return

    group_id = int(callback.data.split(":")[1])
    await _show_remove_members(callback, group_id)


@router.callback_query(F.data.startswith("admin_remove_page:"))
async def remove_member_page_callback(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback, callback.from_user.id):
        return

    _, group_id_text, page_text = callback.data.split(":")
    await _show_remove_members(callback, int(group_id_text), int(page_text))


@router.callback_query(F.data.startswith("admin_pick_remove:"))
async def remove_member_pick_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(callback, callback.from_user.id):
        return

    _, group_id_text, member_id_text = callback.data.split(":")
    group_id = int(group_id_text)
    member_id = int(member_id_text)

    group = await queries.get_group(group_id)
    member = await queries.get_group_member(group_id, member_id)
    if not group or not member:
        await callback.answer("⚠️ Ushbu a'zo endi mavjud emas.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_remove_confirm)
    await state.update_data(
        group_id=group_id,
        group_name=group["name"],
        member_id=member_id,
        member_name=member["display_name"],
    )

    await callback.message.edit_text(
        f"{member['display_name']} ni '{group['name']}' guruhidan o'chirmoqchimisiz?",
        reply_markup=menus.confirmation_keyboard("admin_confirm_remove"),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_confirm_remove", AdminStates.waiting_remove_confirm)
async def remove_member_confirm_callback(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
) -> None:
    if not await _ensure_admin(callback, callback.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    member_id = data["member_id"]
    group_id = data["group_id"]
    group_name = data["group_name"]
    member_name = data["member_name"]

    await callback.message.edit_text("⏳ Iltimos kuting...")
    await queries.remove_member_from_group(group_id, member_id)
    await state.clear()

    try:
        await bot.send_message(
            chat_id=member_id,
            text=f"Siz '{group_name}' guruhidan chiqarildingiz.",
        )
    except TelegramForbiddenError:
        pass
    except TelegramAPIError:
        pass

    await callback.message.edit_text(
        f"✅ {member_name} '{group_name}' guruhidan chiqarildi.",
        reply_markup=menus.back_to_menu_inline(),
    )
    await callback.answer()


@router.message(F.text == "📋 Guruhlar")
async def manage_groups_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await _ensure_admin(message, message.from_user.id):
        return

    groups = await queries.get_groups_overview(message.from_user.id)
    if not groups:
        await message.answer("⚠️ Sizda hali hech qanday guruh yo'q. Avvalo guruh yarating.")
        return

    lines = ["📋 Sizning guruhlaringiz", ""]
    for group in groups:
        lines.extend(
            [
                f"• {group['name']}",
                f"  A'zolar: {group['member_count']}",
                f"  Faol qarzlar jami: {format_amount(group['active_total'])}",
                f"  Yaratilgan: {format_timestamp(group['created_at'])}",
                "",
            ]
        )

    await message.answer("\n".join(lines).strip())
