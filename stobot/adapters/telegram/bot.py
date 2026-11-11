"""Адаптер Telegram: переводит сообщения Telegram в вызовы BotApp и обратно.

Здесь — всё, что относится к Telegram (кнопки, редактирование сообщений,
лимиты). Логики бота здесь нет. Для WhatsApp будет такой же файл
adapters/whatsapp/bot.py, а core/ останется без изменений.
"""

from __future__ import annotations

import logging

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from stobot import texts
from stobot.core.app import BotApp
from stobot.core.models import User
from stobot.core.replies import Reply, Response

log = logging.getLogger(__name__)

TELEGRAM_TEXT_LIMIT = 4096

COMMANDS = [
    BotCommand("cart", "Общая корзина"),
    BotCommand("car", "Машина: /car Камри 123ABC01"),
    BotCommand("orders", "Последние заказы"),
    BotCommand("search", "Поиск по артикулу"),
    BotCommand("help", "Как пользоваться"),
    BotCommand("cancel", "Отменить ввод"),
]


class TelegramAdapter:
    def __init__(self, app: BotApp, admin_ids: frozenset[int], master_ids: frozenset[int]):
        self.app = app
        self.admin_ids = admin_ids
        self.master_ids = master_ids

    # --- Кто пишет ---

    def _user(self, update: Update) -> User:
        tg = update.effective_user
        assert tg is not None
        name = " ".join(filter(None, [tg.first_name, tg.last_name])) or str(tg.id)
        return User(
            id=tg.id,
            name=name,
            is_admin=tg.id in self.admin_ids,
            is_master=tg.id in self.master_ids,
        )

    # --- Обработчики Telegram ---

    async def on_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None or not message.text:
            return
        head, _, args = message.text.partition(" ")
        command = head.lstrip("/").split("@")[0]  # /cart@MyBot -> cart
        response = await self.app.handle_command(self._user(update), command, args)
        await self._send(update, context, response)

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None or not message.text:
            return
        response = await self.app.handle_text(self._user(update), message.text)
        await self._send(update, context, response)

    async def on_other(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Сюда позже добавится расшифровка голосовых: голос → текст → app.handle_text
        message = update.effective_message
        if message:
            await message.reply_text("Пока я понимаю только текст. Пришлите артикул или название.")

    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None or query.data is None:
            return
        response = await self.app.handle_action(self._user(update), query.data)
        # Telegram требует ответить на нажатие, иначе кнопка «крутится»
        await query.answer(response.popup or None)
        await self._send(update, context, response)

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("Unhandled error", exc_info=context.error)
        if isinstance(update, Update) and update.effective_chat:
            try:
                await context.bot.send_message(update.effective_chat.id, texts.INTERNAL_ERROR)
            except Exception:  # noqa: BLE001 — уже ничего не сделать, ошибка в логе
                pass

    # --- Отправка ответов ---

    @staticmethod
    def _keyboard(reply: Reply) -> InlineKeyboardMarkup | None:
        if not reply.buttons:
            return None
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(b.text, callback_data=b.action) for b in row]
                for row in reply.buttons
            ]
        )

    @staticmethod
    def _split(text: str) -> list[str]:
        """Делит длинный текст на части по 4096 символов (лимит Telegram) по переносам строк."""
        if len(text) <= TELEGRAM_TEXT_LIMIT:
            return [text]
        parts, current = [], ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > TELEGRAM_TEXT_LIMIT:
                parts.append(current)
                current = ""
            current += line + "\n"
        if current:
            parts.append(current)
        return parts

    async def _send(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, response: Response
    ) -> None:
        chat = update.effective_chat
        query = update.callback_query
        for reply in response.replies:
            keyboard = self._keyboard(reply)
            chunks = self._split(reply.text)
            if reply.edit and query and query.message and len(chunks) == 1:
                try:
                    await query.edit_message_text(
                        chunks[0], parse_mode=ParseMode.HTML, reply_markup=keyboard
                    )
                    continue
                except BadRequest as e:
                    if "not modified" in str(e).lower():
                        continue  # ничего не изменилось — это нормально
                    log.warning("edit failed, sending new message: %s", e)
            if chat is None:
                continue
            for i, chunk in enumerate(chunks):
                last = i == len(chunks) - 1
                await context.bot.send_message(
                    chat.id,
                    chunk,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard if last else None,
                )

        for note in response.notifications:
            try:
                await context.bot.send_message(
                    note.user_id,
                    note.reply.text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=self._keyboard(note.reply),
                )
            except Forbidden:
                # Человек ещё ни разу не писал боту — Telegram не даёт написать ему первым
                log.info("cannot notify user %s: bot not started", note.user_id)
            except BadRequest as e:
                log.warning("cannot notify user %s: %s", note.user_id, e)


def build_application(
    token: str, app: BotApp, admin_ids: frozenset[int], master_ids: frozenset[int]
) -> Application:
    adapter = TelegramAdapter(app, admin_ids, master_ids)

    async def post_init(application: Application) -> None:
        # Меню команд рядом с полем ввода
        await application.bot.set_my_commands(COMMANDS)

    application = Application.builder().token(token).post_init(post_init).build()
    application.add_handler(MessageHandler(filters.COMMAND, adapter.on_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, adapter.on_text))
    application.add_handler(CallbackQueryHandler(adapter.on_button))
    application.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, adapter.on_other))
    application.add_error_handler(adapter.on_error)
    return application
