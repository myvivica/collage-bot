"""
Collage Bot — Telegram бот для создания коллажей 2×2.

Логика:
  - Помощница отправляет фото файлами (Documents) или сжатыми (Photo)
  - После 4-го фото бот автоматически создаёт коллаж и отправляет обратно
  - /clear — сбросить накопленные фото и начать заново
  - /status — сколько фото уже накоплено
"""

import asyncio
import io
import logging
import os
from collections import defaultdict

from PIL import Image
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]

CANVAS_W = 900
CANVAS_H = 1200
GAP = 4
PHOTOS_NEEDED = 4

# Хранилище фото по chat_id: {chat_id: [PIL.Image, ...]}
pending: dict[int, list[Image.Image]] = defaultdict(list)


# ── Создание коллажа ─────────────────────────────────────────────────────────

def fit_cell(img: Image.Image, cell_w: int, cell_h: int) -> Image.Image:
    img = img.copy()
    img.thumbnail((cell_w, cell_h), Image.LANCZOS)
    cell = Image.new("RGB", (cell_w, cell_h), (255, 255, 255))
    ox = (cell_w - img.width) // 2
    oy = (cell_h - img.height) // 2
    cell.paste(img, (ox, oy))
    return cell


def make_collage(images: list[Image.Image]) -> bytes:
    """2×2 коллаж. Если < 4 фото — повторяем чтобы заполнить."""
    cw = (CANVAS_W - GAP * 3) // 2
    ch = (CANVAS_H - GAP * 3) // 2
    tiles = [images[i % len(images)] for i in range(PHOTOS_NEEDED)]

    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (248, 248, 248))
    positions = [
        (GAP,           GAP),
        (GAP * 2 + cw,  GAP),
        (GAP,           GAP * 2 + ch),
        (GAP * 2 + cw,  GAP * 2 + ch),
    ]
    for tile, (px, py) in zip(tiles, positions):
        canvas.paste(fit_cell(tile, cw, ch), (px, py))

    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=95)
    buf.seek(0)
    return buf.read()


# ── Хэндлеры ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Отправь 4 фото *файлами* — я сразу сделаю коллаж 2×2.\n\n"
        "Можно по одному или альбомом. Фото лучше слать как *Файл* "
        "(в Telegram: прикрепить → Файл), тогда качество не потеряется.\n\n"
        "Команды:\n"
        "/status — сколько фото уже накоплено\n"
        "/clear — сбросить и начать заново",
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    n = len(pending[chat_id])
    if n == 0:
        await update.message.reply_text("📭 Фото ещё нет. Отправляй!")
    else:
        await update.message.reply_text(
            f"📸 Накоплено: {n}/{PHOTOS_NEEDED}. "
            f"Осталось отправить: {PHOTOS_NEEDED - n}."
        )


async def cmd_clear(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    pending[chat_id].clear()
    await update.message.reply_text("🗑 Сброшено! Отправляй фото заново.")


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    msg = update.message

    # Получаем file_id — поддерживаем и Document и Photo
    if msg.document and msg.document.mime_type and "image" in msg.document.mime_type:
        file_id = msg.document.file_id
    elif msg.photo:
        file_id = msg.photo[-1].file_id  # самое большое из сжатых
    else:
        return  # не фото — игнорируем

    # Скачиваем
    file = await context.bot.get_file(file_id)
    data = await file.download_as_bytearray()

    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as e:
        logger.warning("Не удалось открыть фото: %s", e)
        await msg.reply_text("⚠️ Не удалось прочитать файл. Попробуй другой формат.")
        return

    pending[chat_id].append(img)
    n = len(pending[chat_id])
    logger.info("chat=%d фото %d/%d", chat_id, n, PHOTOS_NEEDED)

    if n < PHOTOS_NEEDED:
        remaining = PHOTOS_NEEDED - n
        await msg.reply_text(f"✅ {n}/{PHOTOS_NEEDED} — ещё {remaining} {'фото' if remaining > 1 else 'фото'}.")
        return

    # Достигли 4 — делаем коллаж
    images = pending[chat_id][:PHOTOS_NEEDED]
    pending[chat_id] = pending[chat_id][PHOTOS_NEEDED:]  # остаток (если прислали > 4)
    leftover = len(pending[chat_id])

    await msg.reply_text("⏳ Делаю коллаж…")

    try:
        collage_bytes = make_collage(images)
    except Exception as e:
        logger.error("Ошибка создания коллажа: %s", e)
        await msg.reply_text("❌ Ошибка при создании коллажа. Попробуй ещё раз.")
        return

    await msg.reply_document(
        document=io.BytesIO(collage_bytes),
        filename="collage.jpg",
        caption="🖼 Коллаж готов!" + (
            f"\n\n📸 Осталось в буфере: {leftover} фото."
            if leftover else ""
        ),
    )


# ── Запуск ───────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(
        MessageHandler(
            (filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND,
            handle_media,
        )
    )

    logger.info("Бот запущен (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
