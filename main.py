from __future__ import annotations

import asyncio
import fcntl
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import DB_PATH, load_settings
from db import init_db
from db import queries
from handlers import routers
from middlewares import GroupCheckMiddleware


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def ensure_single_instance(pid_file: Path):
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(pid_file, "a+")

    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        raise RuntimeError("Another bot instance is already running.")

    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file


async def main() -> None:
    settings = load_settings()
    base_dir = Path(__file__).resolve().parent
    pid_file = base_dir / ".bot.pid"

    lock_file = ensure_single_instance(pid_file)
    try:
        init_db(DB_PATH)
        queries.sync_admins(settings.admin_ids)

        bot = Bot(token=settings.bot_token)
        dispatcher = Dispatcher(storage=MemoryStorage())

        group_check = GroupCheckMiddleware()
        dispatcher.message.middleware(group_check)
        dispatcher.callback_query.middleware(group_check)

        for router in routers:
            dispatcher.include_router(router)

        me = await bot.get_me()
        logger.info("Bot started as @%s", me.username or me.id)

        try:
            await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
        finally:
            await bot.session.close()
    finally:
        lock_file.close()
        if pid_file.exists():
            pid_file.unlink()


if __name__ == "__main__":
    asyncio.run(main())
