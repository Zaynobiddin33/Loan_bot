from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.types import CallbackQuery, Message, TelegramObject

from db import queries
from keyboards.menus import main_menu_keyboard


class GroupCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        is_admin = await queries.is_admin(user.id)
        user_groups = await queries.get_user_groups(user.id)
        data["is_admin"] = is_admin
        data["user_groups"] = user_groups

        if get_flag(data, "member_required") and not user_groups:
            text = (
                "👋 Siz hali hech bir guruhga qo'shilmagansiz.\n\n"
                "Avval admindan sizni guruhga qo'shishini so'rang, keyin /start ni yana yuboring."
            )

            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
                return None

            if isinstance(event, Message):
                await event.answer(text, reply_markup=main_menu_keyboard(is_admin=is_admin))
                return None

        return await handler(event, data)
