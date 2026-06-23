"""
Collage Bot — коллажи 2×2 + рекомендации трусиков /recs.
"""

import asyncio
import base64
import io
import logging
import os
from collections import defaultdict
from pathlib import Path

from PIL import Image
from card_template import build_html, render_card
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]

BASE_DIR = Path(__file__).parent

# ── Коллаж 2×2 ───────────────────────────────────────────────────────────────

CANVAS_W, CANVAS_H = 900, 1200
GAP = 4
PHOTOS_NEEDED = 4
pending: dict[int, list[Image.Image]] = defaultdict(list)


def fit_cell(img: Image.Image, cell_w: int, cell_h: int) -> Image.Image:
    img = img.copy()
    img.thumbnail((cell_w, cell_h), Image.LANCZOS)
    cell = Image.new("RGB", (cell_w, cell_h), (255, 255, 255))
    cell.paste(img, ((cell_w - img.width) // 2, (cell_h - img.height) // 2))
    return cell


def make_collage(images: list[Image.Image]) -> bytes:
    cw = (CANVAS_W - GAP * 3) // 2
    ch = (CANVAS_H - GAP * 3) // 2
    tiles = [images[i % len(images)] for i in range(PHOTOS_NEEDED)]
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (248, 248, 248))
    positions = [(GAP, GAP), (GAP*2+cw, GAP), (GAP, GAP*2+ch), (GAP*2+cw, GAP*2+ch)]
    for tile, pos in zip(tiles, positions):
        canvas.paste(fit_cell(tile, cw, ch), pos)
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=95)
    buf.seek(0)
    return buf.read()


# ── Рекомендации /recs ────────────────────────────────────────────────────────

PHOTO1, STYLE1, PHOTO2, STYLE2 = range(4)

PHOTO_FILTER = (filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND

STYLES = ["Танга", "Бразильяна", "Стринги"]
STYLE_KB = ReplyKeyboardMarkup([[s] for s in STYLES], one_time_keyboard=True, resize_keyboard=True)


async def _download_photo(msg, context) -> bytes | None:
    """Скачивает фото из сообщения, возвращает bytes или None."""
    if msg.document and msg.document.mime_type and "image" in msg.document.mime_type:
        file_id = msg.document.file_id
    elif msg.photo:
        file_id = msg.photo[-1].file_id
    else:
        return None
    file = await context.bot.get_file(file_id)
    return bytes(await file.download_as_bytearray())


def make_recs_card(img1_bytes: bytes, style1: str, img2_bytes: bytes, style2: str) -> bytes:
    b64_1 = base64.b64encode(img1_bytes).decode()
    b64_2 = base64.b64encode(img2_bytes).decode()
    html = build_html(style1=style1, photo_b64_1=b64_1, style2=style2, photo_b64_2=b64_2)
    return render_card(html)


# ── Хэндлеры коллажа ─────────────────────────────────────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "📸 *Коллаж 2×2* — отправь 4 фото файлами.\n"
        "👙 *Рекомендации* — /recs\n\n"
        "/status — буфер фото\n"
        "/clear — сброс",
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    n = len(pending[update.effective_chat.id])
    if n == 0:
        await update.message.reply_text("📭 Фото ещё нет. Отправляй!")
    else:
        await update.message.reply_text(f"📸 {n}/{PHOTOS_NEEDED}. Осталось: {PHOTOS_NEEDED - n}.")


async def cmd_clear(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    pending[update.effective_chat.id].clear()
    await update.message.reply_text("🗑 Сброшено!")


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    msg = update.message
    if msg.document and msg.document.mime_type and "image" in msg.document.mime_type:
        file_id = msg.document.file_id
    elif msg.photo:
        file_id = msg.photo[-1].file_id
    else:
        return
    file = await context.bot.get_file(file_id)
    data = await file.download_as_bytearray()
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as e:
        logger.warning("Ошибка чтения фото: %s", e)
        await msg.reply_text("⚠️ Не удалось прочитать файл.")
        return
    pending[chat_id].append(img)
    n = len(pending[chat_id])
    if n < PHOTOS_NEEDED:
        await msg.reply_text(f"✅ {n}/{PHOTOS_NEEDED} — ещё {PHOTOS_NEEDED - n}.")
        return
    images = pending[chat_id][:PHOTOS_NEEDED]
    pending[chat_id] = pending[chat_id][PHOTOS_NEEDED:]
    leftover = len(pending[chat_id])
    await msg.reply_text("⏳ Делаю коллаж…")
    try:
        collage_bytes = make_collage(images)
    except Exception as e:
        logger.error("Ошибка коллажа: %s", e)
        await msg.reply_text("❌ Ошибка. Попробуй ещё раз.")
        return
    await msg.reply_document(
        document=io.BytesIO(collage_bytes),
        filename="collage.jpg",
        caption="🖼 Готово!" + (f"\n📸 В буфере: {leftover}." if leftover else ""),
    )


# ── Хэндлеры /recs ───────────────────────────────────────────────────────────

async def cmd_recs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "👙 *Рекомендации трусиков*\n\n"
        "Шаг 1/4 — загрузи фото для *левой* карточки:",
        parse_mode="Markdown",
    )
    return PHOTO1


async def got_photo1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = await _download_photo(update.message, context)
    if data is None:
        await update.message.reply_text("⚠️ Отправь фото файлом или картинкой")
        return PHOTO1
    context.user_data["img1"] = data
    await update.message.reply_text(
        "✅ Фото получено\n\nШаг 2/4 — выбери фасон для *левой* карточки:",
        parse_mode="Markdown",
        reply_markup=STYLE_KB,
    )
    return STYLE1


async def got_style1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    style = (update.message.text or "").strip()
    if style not in STYLES:
        await update.message.reply_text(
            "⚠️ Выбери фасон из списка", reply_markup=STYLE_KB
        )
        return STYLE1
    context.user_data["style1"] = style
    await update.message.reply_text(
        f"✅ Левая карточка: *{style}*\n\n"
        "Шаг 3/4 — загрузи фото для *правой* карточки:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return PHOTO2


async def got_photo2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = await _download_photo(update.message, context)
    if data is None:
        await update.message.reply_text("⚠️ Отправь фото файлом или картинкой")
        return PHOTO2
    context.user_data["img2"] = data
    await update.message.reply_text(
        "✅ Фото получено\n\nШаг 4/4 — выбери фасон для *правой* карточки:",
        parse_mode="Markdown",
        reply_markup=STYLE_KB,
    )
    return STYLE2


async def got_style2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    style = (update.message.text or "").strip()
    if style not in STYLES:
        await update.message.reply_text(
            "⚠️ Выбери фасон из списка", reply_markup=STYLE_KB
        )
        return STYLE2
    style2 = style
    img1 = context.user_data["img1"]
    style1 = context.user_data["style1"]
    img2 = context.user_data["img2"]
    await update.message.reply_text(
        f"✅ Правая карточка: *{style2}*\n\n⏳ Генерирую карточку…",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    loop = asyncio.get_event_loop()
    try:
        card_bytes = await loop.run_in_executor(
            None, make_recs_card, img1, style1, img2, style2
        )
    except Exception as e:
        logger.error("Ошибка генерации карточки: %s", e)
        await update.message.reply_text("❌ Ошибка генерации. Попробуй ещё раз.")
        return ConversationHandler.END
    await update.message.reply_document(
        document=io.BytesIO(card_bytes),
        filename="recs.jpg",
        caption=f"Левая: {style1} · Правая: {style2}",
    )
    return ConversationHandler.END


async def cancel_recs(update: Update, _: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


# ── Запуск ───────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    recs_handler = ConversationHandler(
        entry_points=[CommandHandler("recs", cmd_recs)],
        states={
            PHOTO1: [MessageHandler(PHOTO_FILTER, got_photo1)],
            STYLE1: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_style1)],
            PHOTO2: [MessageHandler(PHOTO_FILTER, got_photo2)],
            STYLE2: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_style2)],
        },
        fallbacks=[CommandHandler("cancel", cancel_recs)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(recs_handler)
    app.add_handler(
        MessageHandler((filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND, handle_media)
    )

    logger.info("Бот запущен…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
