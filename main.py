"""
Collage Bot — коллажи 2×2 + рекомендации трусиков /recs.
"""

import asyncio
import io
import logging
import os
import urllib.request
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from telegram import Update
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
FONT_PATH = BASE_DIR / "fonts" / "Oranienbaum.ttf"
LOGO_PATH = BASE_DIR / "assets" / "vivica_logo.png"

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

# Цвета Vivica
BG          = (255, 236, 215)   # #ffecd7
CARD_BG     = (255, 248, 240)   # #fff8f0
BURGUNDY    = (137, 15,  30)    # #890f1e
LABEL_CLR   = (176, 144, 112)   # #b09070
BORDER_CLR  = (233, 217, 199)   # #e9d9c7
BTN_TEXT    = (255, 236, 215)   # #ffecd7

# Размеры (HTML 360×480 × 2.5 = 900×1200)
S = 2.5
PAD        = int(40)    # боковые отступы
PROD_GAP   = int(25)    # зазор между карточками
PROD_W     = (900 - PAD * 2 - PROD_GAP) // 2   # 397px
PHOTO_H    = int(PROD_W * 4 / 3)                # 529px
INFO_H     = 220                                 # высота блока под фото
PROD_H     = PHOTO_H + INFO_H                   # 749px
HEADER_H   = 237                                 # высота шапки (top 125 + text + bottom 60)
LOGO_SIZE  = 180                                 # высота лого


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FONT_PATH), size)
    except Exception:
        return ImageFont.load_default()


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


def _fetch_image(url: str) -> Image.Image | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return Image.open(io.BytesIO(r.read())).convert("RGB")
    except Exception as e:
        logger.warning("Не удалось загрузить фото %s: %s", url, e)
        return None


def _crop_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Обрезка с сохранением пропорций (cover)."""
    if img.width / img.height > w / h:
        nw = int(img.height * w / h)
        img = img.crop(((img.width - nw) // 2, 0, (img.width + nw) // 2, img.height))
    else:
        nh = int(img.width * h / w)
        img = img.crop((0, (img.height - nh) // 2, img.width, (img.height + nh) // 2))
    return img.resize((w, h), Image.LANCZOS)


def _paste_rounded_top(canvas: Image.Image, photo: Image.Image,
                        x: int, y: int, w: int, h: int, r: int) -> None:
    """Вставить фото со скруглёнными верхними углами."""
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, w, h], radius=r, fill=255)
    md.rectangle([0, r, w, h], fill=255)
    canvas.paste(photo, (x, y), mask)


def make_recs_card(nm1: int, style1: str, nm2: int, style2: str) -> bytes:
    photo1 = _fetch_image(wb_photo_url(nm1))
    photo2 = _fetch_image(wb_photo_url(nm2))

    # Шрифты
    f_header = _load_font(38)
    f_label  = _load_font(22)
    f_name   = _load_font(32)
    f_btn    = _load_font(24)
    f_logo   = _load_font(62)

    # Холст
    canvas = Image.new("RGB", (900, 1200), BG)
    draw = ImageDraw.Draw(canvas)

    # Внешняя рамка карточки
    draw.rounded_rectangle([0, 0, 899, 1199], radius=40, outline=BORDER_CLR, width=2)

    # Заголовок
    header_text = "Выберите свой фасон трусиков"
    bbox = draw.textbbox((0, 0), header_text, font=f_header)
    tw = bbox[2] - bbox[0]
    draw.text(((900 - tw) // 2, 115), header_text, font=f_header, fill=BURGUNDY)

    # Y-позиции карточек (flex-эмуляция: spacer-top 1.4 из свободного места)
    free = 1200 - HEADER_H - PROD_H - LOGO_SIZE
    spacer_top = int(free * 1.4 / 2.4)
    prod_y = HEADER_H + spacer_top

    for i, (nm, style, photo) in enumerate([(nm1, style1, photo1), (nm2, style2, photo2)]):
        x = PAD + i * (PROD_W + PROD_GAP)

        # Фон карточки продукта
        draw.rounded_rectangle(
            [x, prod_y, x + PROD_W, prod_y + PROD_H],
            radius=30, fill=CARD_BG, outline=BORDER_CLR, width=1
        )

        # Фото
        if photo:
            ph = _crop_cover(photo, PROD_W, PHOTO_H)
            _paste_rounded_top(canvas, ph, x, prod_y, PROD_W, PHOTO_H, 30)
        else:
            draw.rounded_rectangle(
                [x, prod_y, x + PROD_W, prod_y + PHOTO_H],
                radius=30, fill=(220, 210, 200)
            )

        # Инфо-блок
        iy = prod_y + PHOTO_H
        # Лейбл
        draw.text((x + 25, iy + 22), "КОМПЛЕКТ БЕЛЬЯ", font=f_label, fill=LABEL_CLR)
        # Название
        name_text = f"с трусиками {style}"
        draw.text((x + 25, iy + 58), name_text, font=f_name, fill=BURGUNDY)
        # Кнопка
        by = iy + INFO_H - 68
        draw.rounded_rectangle([x + 25, by, x + PROD_W - 25, by + 48], radius=14, fill=BURGUNDY)
        bbox_btn = draw.textbbox((0, 0), "ПЕРЕЙТИ →", font=f_btn)
        bw = bbox_btn[2] - bbox_btn[0]
        bh = bbox_btn[3] - bbox_btn[1]
        draw.text(
            (x + 25 + (PROD_W - 50 - bw) // 2, by + (48 - bh) // 2 - bbox_btn[1]),
            "ПЕРЕЙТИ →", font=f_btn, fill=BTN_TEXT
        )

    # Лого Vivica внизу
    logo_y = prod_y + PROD_H + (1200 - prod_y - PROD_H - LOGO_SIZE) // 2 - 15
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        # Масштабируем до нужной высоты
        lh = LOGO_SIZE
        lw = int(logo.width * lh / logo.height)
        logo = logo.resize((lw, lh), Image.LANCZOS)
        canvas.paste(logo, ((900 - lw) // 2, logo_y), logo)
    else:
        bbox_logo = draw.textbbox((0, 0), "Vivica", font=f_logo)
        lw = bbox_logo[2] - bbox_logo[0]
        draw.text(((900 - lw) // 2, logo_y), "Vivica", font=f_logo, fill=BURGUNDY)

    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=95)
    buf.seek(0)
    return buf.read()


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
