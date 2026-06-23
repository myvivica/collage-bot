"""
Panties Bot — рекомендации трусиков /recs.
"""

import asyncio
import base64
import io
import logging
import os
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

# ── /recs ─────────────────────────────────────────────────────────────────────

PHOTO1, STYLE1, PHOTO2, STYLE2 = range(4)

PHOTO_FILTER = (filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND

STYLES = ["Танга", "Бразильяна", "Стринги"]
STYLE_KB = ReplyKeyboardMarkup([[s] for s in STYLES], one_time_keyboard=True, resize_keyboard=True)


async def _download_photo(msg, context) -> bytes | None:
    if msg.document and msg.document.mime_type and "image" in msg.document.mime_type:
        file_id = msg.document.file_id
    elif msg.photo:
        file_id = msg.photo[-1].file_id
    else:
        return None
    try:
        file = await asyncio.wait_for(context.bot.get_file(file_id), timeout=30.0)
        data = await asyncio.wait_for(file.download_as_bytearray(), timeout=30.0)
        return bytes(data)
    except asyncio.TimeoutError:
        logger.error("Таймаут скачивания фото file_id=%s", file_id)
        return None


def _resize(data: bytes, max_side: int = 1200) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def make_recs_card(img1_bytes: bytes, style1: str, img2_bytes: bytes, style2: str) -> bytes:
    b64_1 = base64.b64encode(_resize(img1_bytes)).decode()
    b64_2 = base64.b64encode(_resize(img2_bytes)).decode()
    html = build_html(style1=style1, photo_b64_1=b64_1, style2=style2, photo_b64_2=b64_2)
    return render_card(html)


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👙 *Vivica — карточка рекомендаций*\n\n"
        "Создаёт карточку с двумя фасонами трусиков для публикации.\n\n"
        "*Как использовать:*\n"
        "1. Отправь /recs\n"
        "2. Загрузи фото левой карточки\n"
        "3. Выбери фасон из списка\n"
        "4. Загрузи фото правой карточки\n"
        "5. Выбери фасон из списка\n"
        "6. Получи готовую карточку\n\n"
        "/recs — начать\n"
        "/cancel — отменить в любой момент",
        parse_mode="Markdown",
    )


async def cmd_recs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Шаг 1/4 — загрузи фото для *левой* карточки:",
        parse_mode="Markdown",
    )
    return PHOTO1


async def got_photo1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = await _download_photo(update.message, context)
    if data is None:
        await update.message.reply_text("⚠️ Не удалось загрузить фото. Отправь ещё раз.")
        return PHOTO1
    context.user_data["img1"] = data
    await update.message.reply_text(
        "Шаг 2/4 — выбери фасон для *левой* карточки:",
        parse_mode="Markdown",
        reply_markup=STYLE_KB,
    )
    return STYLE1


async def got_style1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    style = (update.message.text or "").strip()
    if style not in STYLES:
        await update.message.reply_text("⚠️ Выбери фасон из списка", reply_markup=STYLE_KB)
        return STYLE1
    context.user_data["style1"] = style
    await update.message.reply_text(
        f"✅ Левая: *{style}*\n\nШаг 3/4 — загрузи фото для *правой* карточки:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return PHOTO2


async def got_photo2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = await _download_photo(update.message, context)
    if data is None:
        await update.message.reply_text("⚠️ Не удалось загрузить фото. Отправь ещё раз.")
        return PHOTO2
    context.user_data["img2"] = data
    await update.message.reply_text(
        "Шаг 4/4 — выбери фасон для *правой* карточки:",
        parse_mode="Markdown",
        reply_markup=STYLE_KB,
    )
    return STYLE2


async def got_style2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    style = (update.message.text or "").strip()
    if style not in STYLES:
        await update.message.reply_text("⚠️ Выбери фасон из списка", reply_markup=STYLE_KB)
        return STYLE2
    img1 = context.user_data["img1"]
    style1 = context.user_data["style1"]
    img2 = context.user_data["img2"]
    await update.message.reply_text(
        f"✅ Правая: *{style}*\n\n⏳ Генерирую карточку…",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    loop = asyncio.get_event_loop()
    try:
        card_bytes = await asyncio.wait_for(
            loop.run_in_executor(None, make_recs_card, img1, style1, img2, style),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        logger.error("Таймаут генерации карточки")
        await update.message.reply_text("❌ Генерация заняла слишком долго. Попробуй ещё раз.")
        return ConversationHandler.END
    except Exception as e:
        logger.error("Ошибка генерации карточки: %s", e)
        await update.message.reply_text("❌ Ошибка генерации. Попробуй ещё раз.")
        return ConversationHandler.END
    await update.message.reply_document(
        document=io.BytesIO(card_bytes),
        filename="recs.jpg",
        caption=f"{style1} · {style}",
    )
    return ConversationHandler.END


async def cancel_recs(update: Update, _: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Необработанная ошибка: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Что-то пошло не так. Начни заново — /recs",
            reply_markup=ReplyKeyboardRemove(),
        )


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
    app.add_handler(recs_handler)
    app.add_error_handler(error_handler)

    logger.info("Бот запущен…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
