from aiogram import F, Router
from aiogram.types import Message

from services.qbittorrent import qbittorrent

router = Router()

@router.message(F.text.startswith("magnet:"))
async def handle_magnet(message: Message):
    await message.reply("Adding torrent...")
    success = await qbittorrent.add_magnet(message.text)
    if success:
        await message.reply("Torrent added successfully.")
    else:
        await message.reply("Failed to add torrent. Check qBittorrent connection.")


@router.message(F.document.mime_type == "application/x-bittorrent")
async def handle_torrent_file(message: Message):
    await message.reply("Processing .torrent file...")
    file = await message.bot.get_file(message.document.file_id)
    downloaded = await message.bot.download_file(file.file_path)
    success = await qbittorrent.add_torrent_file(downloaded.read())
    if success:
        await message.reply("Torrent added successfully.")
    else:
        await message.reply("Failed to add torrent. Check qBittorrent connection.")
