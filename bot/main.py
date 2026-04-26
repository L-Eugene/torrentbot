import asyncio
import logging

from aiogram import Bot, Dispatcher

from config import settings
from handlers import status, torrent

logging.basicConfig(level=logging.INFO)


async def main():
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    dp.include_router(torrent.router)
    dp.include_router(status.router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
