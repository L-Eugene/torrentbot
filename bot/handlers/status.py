from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services.qbittorrent import qbittorrent

router = Router()

_STATE_LABELS = {
    "downloading": "downloading",
    "stalledDL": "stalled",
    "uploading": "seeding",
    "pausedDL": "paused",
    "checkingDL": "checking",
    "queuedDL": "queued",
    "error": "error",
}


@router.message(Command("status"))
async def handle_status(message: Message):
    torrents = await qbittorrent.get_torrents()
    if not torrents:
        await message.reply("No active torrents.")
        return

    lines = []
    for t in torrents:
        progress = int(t["progress"] * 100)
        state = _STATE_LABELS.get(t["state"], t["state"])
        name = t["name"][:45] + "…" if len(t["name"]) > 45 else t["name"]
        lines.append(f"• {name} — {progress}% ({state})")

    await message.reply("\n".join(lines))


@router.message(Command("help"))
async def handle_help(message: Message):
    await message.reply(
        "Send a magnet link or a .torrent file to start downloading.\n"
        "/status — list active torrents"
    )
