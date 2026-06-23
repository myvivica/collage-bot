"""
Collage Bot — коллажи 2×2 + рекомендации трусиков /recs.
"""

import asyncio
import io
import logging
import os
from collections import defaultdict
from pathlib import Path

from PIL import Image
from telegram import Update
from card_template import build_html, render_card
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

# ── Пути к ресурсам ───────────────────────────────────────────────────────────

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

ARTICLE1, ARTICLE2 = range(2)


def _get_basket(vol: int) -> int:
    table = [
        (143,1),(287,2),(431,3),(719,4),(1007,5),(1061,6),(1115,7),(1169,8),
        (1313,9),(1601,10),(1655,11),(1919,12),(2045,13),(2189,14),(2405,15),
        (2621,16),(2837,17),(3053,18),(3269,19),(3485,20),(3701,21),(3917,22),
        (4133,23),(4349,24),(4565,25),(4781,26),(4997,27),(5213,28),(5429,29),
    ]
    for threshold, basket in table:
        if vol <= threshold:
            return basket
    return 30


def wb_photo_url(nm: int) -> str:
    vol = nm // 100_000
    part = nm // 1_000
    basket = _get_basket(vol)
    return f"https://basket-{basket:02d}.wbbasket.ru/vol{vol}/part{part}/{nm}/images/big/1.webp"


def make_recs_card(nm1: int, style1: str, nm2: int, style2: str) -> bytes:
    html = build_html(
        style1=style1,
        photo_url1=wb_photo_url(nm1),
        product_url1=f"https://www.wildberries.ru/catalog/{nm1}/detail.aspx",
        style2=style2,
        photo_url2=wb_photo_url(nm2),
        product_url2=f"https://www.wildberries.ru/catalog/{nm2}/detail.aspx",
    )
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
        "Пришли артикул WB и фасон первого комплекта:\n"
        "`473725009 танга`",
        parse_mode="Markdown",
    )
    return ARTICLE1


def _parse_article_input(text: str) -> tuple[int, str] | None:
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None
    try:
        nm = int(parts[0])
    except ValueError:
        return None
    style = parts[1].strip() if len(parts) > 1 else "—"
    return nm, style


async def got_article1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parsed = _parse_article_input(update.message.text or "")
    if not parsed:
        await update.message.reply_text("⚠️ Формат: `473725009 танга`", parse_mode="Markdown")
        return ARTICLE1
    context.user_data["nm1"], context.user_data["style1"] = parsed
    await update.message.reply_text(
        f"✅ Первый: артикул `{parsed[0]}`, фасон *{parsed[1]}*\n\n"
        "Теперь второй комплект:",
        parse_mode="Markdown",
    )
    return ARTICLE2


async def got_article2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parsed = _parse_article_input(update.message.text or "")
    if not parsed:
        await update.message.reply_text("⚠️ Формат: `398567780 стринги`", parse_mode="Markdown")
        return ARTICLE2
    nm2, style2 = parsed
    nm1 = context.user_data["nm1"]
    style1 = context.user_data["style1"]
    await update.message.reply_text("⏳ Генерирую карточку…")
    loop = asyncio.get_event_loop()
    try:
        card_bytes = await loop.run_in_executor(
            None, make_recs_card, nm1, style1, nm2, style2
        )
    except Exception as e:
        logger.error("Ошибка генерации карточки: %s", e)
        await update.message.reply_text("❌ Ошибка генерации. Попробуй ещё раз.")
        return ConversationHandler.END
    await update.message.reply_document(
        document=io.BytesIO(card_bytes),
        filename="recs.jpg",
        caption=f"с трусиками {style1} vs с трусиками {style2}",
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
            ARTICLE1: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_article1)],
            ARTICLE2: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_article2)],
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
