"""
Panties Bot — рекомендации трусиков /recs.
"""

import asyncio
import base64
import io
import logging
import os
import re
from pathlib import Path

from PIL import Image
import card_template
import info_template
import text_templates
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]

BASE_DIR = Path(__file__).parent
PERSISTENCE_PATH = BASE_DIR / "bot_state.pkl"

# ── states ────────────────────────────────────────────────────────────────────

MAIN_ARTICLE, ARTICLE1, PHOTO1, STYLE1, ARTICLE2, PHOTO2, STYLE2 = range(7)
INFO_ARTICLE, INFO_HERO, INFO_INSETS, INFO_TEXT = range(10, 14)
INFO_TEXT_CUSTOM, INFO_TPL_NAME = range(14, 16)

PHOTO_FILTER = (filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND

STYLES = ["Танга", "Бразильяна", "Стринги"]
STYLE_KB = ReplyKeyboardMarkup([[s] for s in STYLES], one_time_keyboard=True, resize_keyboard=True)

BTN_INFO = "🖼 Инфографика"
BTN_RECS = "👙 Карточка рекомендаций"
BTN_CANCEL = "✖️ Отмена"

MAIN_KB = ReplyKeyboardMarkup(
    [[BTN_INFO], [BTN_RECS]], resize_keyboard=True, is_persistent=True
)
CANCEL_KB = ReplyKeyboardMarkup([[BTN_CANCEL]], resize_keyboard=True, is_persistent=True)

# кнопки главного меню не должны попадать в текстовые поля диалогов
MENU_FILTER = filters.Regex(
    "^(" + "|".join(re.escape(b) for b in (BTN_INFO, BTN_RECS, BTN_CANCEL)) + ")$"
)
TEXT_FILTER = filters.TEXT & ~filters.COMMAND & ~MENU_FILTER


def _get_file_id(msg) -> str | None:
    if msg.document and msg.document.mime_type and "image" in msg.document.mime_type:
        return msg.document.file_id
    if msg.photo:
        return msg.photo[-1].file_id
    return None


async def _download_file_id(file_id: str, context) -> bytes | None:
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
    html = card_template.build_html(
        style1=style1, photo_b64_1=b64_1, style2=style2, photo_b64_2=b64_2
    )
    return card_template.render_card(html)


# ── handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👙 *Vivica — генератор карточек*\n\n"
        f"*{BTN_INFO}* — фото модели + текстовые буллеты + круглые врезки\n"
        f"*{BTN_RECS}* — слайд с двумя фасонами\n\n"
        "Выбери кнопку внизу.",
        parse_mode="Markdown",
        reply_markup=MAIN_KB,
    )


async def cmd_recs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Введи основной артикул\n_(товар, в который добавляем этот слайд)_",
        parse_mode="Markdown",
    )
    return MAIN_ARTICLE


async def got_main_article(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    article = (update.message.text or "").strip()
    if not article:
        await update.message.reply_text("⚠️ Введи артикул")
        return MAIN_ARTICLE
    context.user_data["main_article"] = article
    await update.message.reply_text("Артикул *левой* карточки:", parse_mode="Markdown")
    return ARTICLE1


async def got_article1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    article = (update.message.text or "").strip()
    if not article:
        await update.message.reply_text("⚠️ Введи артикул")
        return ARTICLE1
    context.user_data["article1"] = article
    await update.message.reply_text("Загрузи фото для *левой* карточки:", parse_mode="Markdown")
    return PHOTO1


async def got_photo1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = _get_file_id(update.message)
    if file_id is None:
        await update.message.reply_text("⚠️ Отправь фото файлом или картинкой.")
        return PHOTO1
    context.user_data["fid1"] = file_id
    await update.message.reply_text(
        "Фасон *левой* карточки:",
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
        f"✅ Левая: *{style}*\n\nАртикул *правой* карточки:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ARTICLE2


async def got_article2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    article = (update.message.text or "").strip()
    if not article:
        await update.message.reply_text("⚠️ Введи артикул")
        return ARTICLE2
    context.user_data["article2"] = article
    await update.message.reply_text("Загрузи фото для *правой* карточки:", parse_mode="Markdown")
    return PHOTO2


async def got_photo2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = _get_file_id(update.message)
    if file_id is None:
        await update.message.reply_text("⚠️ Отправь фото файлом или картинкой.")
        return PHOTO2
    context.user_data["fid2"] = file_id
    await update.message.reply_text(
        "Фасон *правой* карточки:",
        parse_mode="Markdown",
        reply_markup=STYLE_KB,
    )
    return STYLE2


async def got_style2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    style = (update.message.text or "").strip()
    if style not in STYLES:
        await update.message.reply_text("⚠️ Выбери фасон из списка", reply_markup=STYLE_KB)
        return STYLE2

    fid1 = context.user_data.get("fid1")
    fid2 = context.user_data.get("fid2")
    style1 = context.user_data.get("style1")
    main_article = context.user_data.get("main_article", "0")
    article1 = context.user_data.get("article1", "0")
    article2 = context.user_data.get("article2", "0")

    if not fid1 or not fid2 or not style1:
        await update.message.reply_text(
            "⚠️ Данные сессии потеряны. Начни заново — /recs",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"✅ Правая: *{style}*\n\n⏳ Генерирую карточку…",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    img1 = await _download_file_id(fid1, context)
    img2 = await _download_file_id(fid2, context)

    if img1 is None or img2 is None:
        await update.message.reply_text("❌ Не удалось скачать фото. Попробуй ещё раз — /recs")
        return ConversationHandler.END

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

    filename = f"{main_article}_{article1}_{article2}.png"
    await update.message.reply_document(
        document=io.BytesIO(card_bytes),
        filename=filename,
        caption=f"{main_article} | {article1} · {article2}",
    )
    return ConversationHandler.END


# ── /info — инфографика «фото + буллеты + круглые врезки» ─────────────────────

INFO_DONE_KB = ReplyKeyboardMarkup([["Готово"]], one_time_keyboard=True, resize_keyboard=True)


def make_info_card(
    hero_bytes: bytes, insets: list[bytes], bullets: list[str], focus: int = 50
) -> bytes:
    hero_resized = _resize(hero_bytes, 1400)
    bg = info_template.bg_color_from_photo(hero_resized)
    html = info_template.build_html(
        photo_b64=base64.b64encode(hero_resized).decode(),
        bullets=bullets,
        insets_b64=[base64.b64encode(_resize(i, 800)).decode() for i in insets],
        bg=bg,
        focus=focus,
    )
    return info_template.render_card(html)


BTN_TPL_CUSTOM = "✏️ Разовый текст"
BTN_TPL_NEW = "➕ Новый шаблон"


def _templates_kb(context: ContextTypes.DEFAULT_TYPE) -> ReplyKeyboardMarkup:
    names = list(text_templates.all_templates(context.bot_data))
    rows = [[n] for n in names] + [[BTN_TPL_CUSTOM], [BTN_TPL_NEW], [BTN_CANCEL]]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def _templates_preview(context: ContextTypes.DEFAULT_TYPE) -> str:
    tpls = text_templates.all_templates(context.bot_data)
    return "\n\n".join(
        "*{}*\n{}".format(name, "\n".join("· " + ln for ln in lines))
        for name, lines in tpls.items()
    )


async def _ask_template(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    await message.reply_text(
        "Текст — выбери шаблон:\n\n" + _templates_preview(context),
        parse_mode="Markdown",
        reply_markup=_templates_kb(context),
    )
    return INFO_TEXT


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Артикул _(для имени файла)_:", parse_mode="Markdown"
    )
    return INFO_ARTICLE


async def info_article(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    article = (update.message.text or "").strip()
    if not article:
        await update.message.reply_text("⚠️ Введи артикул")
        return INFO_ARTICLE
    context.user_data["info_article"] = article
    await update.message.reply_text(
        "Основное фото _(вертикальное, модель)_:", parse_mode="Markdown"
    )
    return INFO_HERO


async def info_hero(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = _get_file_id(update.message)
    if file_id is None:
        await update.message.reply_text("⚠️ Отправь фото файлом или картинкой.")
        return INFO_HERO
    context.user_data["info_hero"] = file_id
    context.user_data["info_insets"] = []
    await update.message.reply_text(
        "Фото для круглых врезок — 1 или 2 штуки.\n"
        "Отправь по одному, потом нажми «Готово».",
        reply_markup=INFO_DONE_KB,
    )
    return INFO_INSETS


async def info_inset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = _get_file_id(update.message)
    if file_id is None:
        await update.message.reply_text("⚠️ Отправь фото файлом или картинкой.")
        return INFO_INSETS
    insets = context.user_data.setdefault("info_insets", [])
    insets.append(file_id)
    if len(insets) >= 2:
        await update.message.reply_text("✅ Две врезки приняты.", reply_markup=ReplyKeyboardRemove())
        return await _ask_template(update.message, context)
    await update.message.reply_text(
        f"✅ Принято ({len(insets)}/2). Ещё одно фото или «Готово».",
        reply_markup=INFO_DONE_KB,
    )
    return INFO_INSETS


async def info_insets_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not context.user_data.get("info_insets"):
        await update.message.reply_text("⚠️ Нужна хотя бы одна врезка.", reply_markup=INFO_DONE_KB)
        return INFO_INSETS
    return await _ask_template(update.message, context)


def _focus_kb(focus: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("◀︎ кадр", callback_data=f"info_focus:{max(0, focus - 15)}"),
            InlineKeyboardButton(f"{focus}%", callback_data="info_focus:noop"),
            InlineKeyboardButton("кадр ▶︎", callback_data=f"info_focus:{min(100, focus + 15)}"),
        ]]
    )


async def _send_info_card(message, context, focus: int) -> None:
    hero = await _download_file_id(context.user_data["info_hero"], context)
    insets = []
    for fid in context.user_data.get("info_insets", []):
        data = await _download_file_id(fid, context)
        if data is not None:
            insets.append(data)

    if hero is None or not insets:
        await message.reply_text("❌ Не удалось скачать фото. Начни заново — /info")
        return

    bullets = context.user_data.get("info_bullets", [])
    loop = asyncio.get_event_loop()
    try:
        png = await asyncio.wait_for(
            loop.run_in_executor(None, make_info_card, hero, insets, bullets, focus),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        logger.error("Таймаут генерации инфографики")
        await message.reply_text("❌ Генерация заняла слишком долго. Попробуй ещё раз — /info")
        return
    except Exception as e:
        logger.error("Ошибка генерации инфографики: %s", e, exc_info=e)
        await message.reply_text("❌ Ошибка генерации. Попробуй ещё раз — /info")
        return

    article = context.user_data.get("info_article", "info")
    await message.reply_document(
        document=io.BytesIO(png),
        filename=f"{article}_info.png",
        caption=f"{article} · кадр {focus}%",
        reply_markup=_focus_kb(focus),
    )


async def info_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор шаблона текста (или переход к ручному вводу)."""
    choice = (update.message.text or "").strip()

    if choice in (BTN_TPL_CUSTOM, BTN_TPL_NEW):
        context.user_data["info_save_tpl"] = choice == BTN_TPL_NEW
        await update.message.reply_text(
            "Строки текста — до 3, каждая с новой строки:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return INFO_TEXT_CUSTOM

    tpls = text_templates.all_templates(context.bot_data)
    if choice not in tpls:
        await update.message.reply_text(
            "⚠️ Выбери шаблон кнопкой", reply_markup=_templates_kb(context)
        )
        return INFO_TEXT

    context.user_data["info_bullets"] = tpls[choice]
    return await _generate_info(update.message, context)


async def info_text_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lines = [ln.strip() for ln in (update.message.text or "").split("\n") if ln.strip()][:3]
    if not lines:
        await update.message.reply_text("⚠️ Введи хотя бы одну строку текста")
        return INFO_TEXT_CUSTOM
    context.user_data["info_bullets"] = lines

    if context.user_data.pop("info_save_tpl", False):
        await update.message.reply_text("Название шаблона:")
        return INFO_TPL_NAME

    return await _generate_info(update.message, context)


async def info_tpl_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()[:40]
    if not name:
        await update.message.reply_text("⚠️ Введи название")
        return INFO_TPL_NAME
    text_templates.save_template(
        context.bot_data, name, context.user_data.get("info_bullets", [])
    )
    await update.message.reply_text(f"✅ Шаблон «{name}» сохранён")
    return await _generate_info(update.message, context)


async def _generate_info(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not context.user_data.get("info_hero"):
        await message.reply_text("⚠️ Данные сессии потеряны. Начни заново.", reply_markup=MAIN_KB)
        return ConversationHandler.END

    await message.reply_text("⏳ Генерирую…", reply_markup=MAIN_KB)
    await _send_info_card(message, context, focus=50)
    return ConversationHandler.END


async def info_focus_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    payload = query.data.split(":", 1)[1]
    if payload == "noop":
        await query.answer("Положение кадра основного фото")
        return
    if not context.user_data.get("info_hero"):
        await query.answer("Сессия потеряна — /info", show_alert=True)
        return
    await query.answer("Пересобираю…")
    await _send_info_card(query.message, context, focus=int(payload))


async def menu_interrupt(update: Update, _: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Текущий диалог прерван. Нажми кнопку ещё раз.", reply_markup=MAIN_KB
    )
    return ConversationHandler.END


async def cancel_recs(update: Update, _: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено.", reply_markup=MAIN_KB)
    return ConversationHandler.END


async def stray_photo(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Выбери, что делаем:", reply_markup=MAIN_KB)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Необработанная ошибка: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Что-то пошло не так. Начни заново.",
            reply_markup=MAIN_KB,
        )


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands(
        [
            BotCommand("info", "Инфографика: фото + буллеты + врезки"),
            BotCommand("recs", "Карточка рекомендаций (два фасона)"),
            BotCommand("templates", "Шаблоны текста"),
            BotCommand("cancel", "Отменить"),
        ]
    )


async def cmd_templates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Шаблоны текста:\n\n" + _templates_preview(context) +
        "\n\nУдалить: /deltpl Название",
        parse_mode="Markdown",
        reply_markup=MAIN_KB,
    )


async def cmd_deltpl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Укажи название: /deltpl Название")
        return
    ok = text_templates.delete_template(context.bot_data, name)
    await update.message.reply_text(
        f"✅ «{name}» удалён" if ok else f"⚠️ «{name}» не найден среди пользовательских"
    )


def build_app() -> Application:
    persistence = PicklePersistence(filepath=str(PERSISTENCE_PATH))
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .persistence(persistence)
        .post_init(post_init)
        .build()
    )

    recs_handler = ConversationHandler(
        entry_points=[
            CommandHandler("recs", cmd_recs),
            MessageHandler(filters.Regex("^" + re.escape(BTN_RECS) + "$"), cmd_recs),
        ],
        states={
            MAIN_ARTICLE: [MessageHandler(TEXT_FILTER, got_main_article)],
            ARTICLE1:     [MessageHandler(TEXT_FILTER, got_article1)],
            PHOTO1:       [MessageHandler(PHOTO_FILTER, got_photo1)],
            STYLE1:       [MessageHandler(TEXT_FILTER, got_style1)],
            ARTICLE2:     [MessageHandler(TEXT_FILTER, got_article2)],
            PHOTO2:       [MessageHandler(PHOTO_FILTER, got_photo2)],
            STYLE2:       [MessageHandler(TEXT_FILTER, got_style2)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_recs),
            MessageHandler(filters.Regex("^" + re.escape(BTN_CANCEL) + "$"), cancel_recs),
            MessageHandler(MENU_FILTER, menu_interrupt),
        ],
        persistent=True,
        name="recs_conv",
    )

    info_handler = ConversationHandler(
        entry_points=[
            CommandHandler("info", cmd_info),
            MessageHandler(filters.Regex("^" + re.escape(BTN_INFO) + "$"), cmd_info),
        ],
        states={
            INFO_ARTICLE: [MessageHandler(TEXT_FILTER, info_article)],
            INFO_HERO:    [MessageHandler(PHOTO_FILTER, info_hero)],
            INFO_INSETS:  [
                MessageHandler(PHOTO_FILTER, info_inset),
                MessageHandler(filters.Regex("^Готово$"), info_insets_done),
            ],
            INFO_TEXT:        [MessageHandler(TEXT_FILTER, info_text)],
            INFO_TEXT_CUSTOM: [MessageHandler(TEXT_FILTER, info_text_custom)],
            INFO_TPL_NAME:    [MessageHandler(TEXT_FILTER, info_tpl_name)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_recs),
            MessageHandler(filters.Regex("^" + re.escape(BTN_CANCEL) + "$"), cancel_recs),
            MessageHandler(MENU_FILTER, menu_interrupt),
        ],
        persistent=True,
        name="info_conv",
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("templates", cmd_templates))
    app.add_handler(CommandHandler("deltpl", cmd_deltpl))
    app.add_handler(recs_handler)
    app.add_handler(info_handler)
    app.add_handler(CallbackQueryHandler(info_focus_cb, pattern=r"^info_focus:"))
    app.add_handler(
        MessageHandler(filters.Regex("^" + re.escape(BTN_CANCEL) + "$"), cancel_recs)
    )
    app.add_handler(MessageHandler(PHOTO_FILTER, stray_photo))
    app.add_error_handler(error_handler)

    return app


def main() -> None:
    app = build_app()
    logger.info("Бот запущен…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
