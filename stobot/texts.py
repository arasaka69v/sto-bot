"""Все тексты бота в одном месте — чтобы легко поправить формулировки."""

from __future__ import annotations

from decimal import Decimal
from html import escape

# --- Помощники форматирования ---


def money(value: Decimal, currency: str = "₸") -> str:
    """Decimal('38500') -> '38 500 ₸'."""
    if value == value.to_integral_value():
        text = f"{int(value):,}".replace(",", " ")
    else:
        text = f"{value:,.2f}".replace(",", " ")
    return f"{text} {currency}"


def esc(text: str | None) -> str:
    """Экранируем текст от поставщика/мастера, чтобы символы < > & не сломали разметку."""
    return escape(text or "")


def days(n: int) -> str:
    if n <= 0:
        return "сегодня"
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} дня"
    return f"{n} дней"


# --- Тексты ---

HELP = (
    "👋 <b>Бот для заказа запчастей</b>\n\n"
    "<b>Как искать:</b>\n"
    "• Просто пришлите артикул: <code>04465-33471</code>\n"
    "• Или название детали: <i>колодки перед</i>, <i>граната</i>\n\n"
    "<b>Машина:</b>\n"
    "• <code>/car Камри 123ABC01</code> — всё, что добавите дальше, привяжется к ней\n"
    "• <code>/car</code> — текущая машина и список\n"
    "• <code>/car off</code> — отвязать\n\n"
    "<b>Корзина и заказы:</b>\n"
    "• /cart — общая корзина\n"
    "• /orders — последние заказы\n"
    "• <code>/orders 123ABC01</code> — что заказывали для машины\n\n"
    "/cancel — отменить ввод, /help — эта подсказка"
)

NO_ACCESS = (
    "⛔ У вас нет доступа к этому боту.\n\n"
    "Ваш Telegram ID: <code>{user_id}</code>\n"
    "Передайте его ответственному — он добавит вас в настройки."
)

SUPPLIER_DOWN = (
    "😕 Поставщик сейчас не отвечает. Попробуйте через пару минут.\n"
    "Если повторяется — сообщите ответственному."
)
NOT_FOUND = (
    "🔍 По артикулу <b>{article}</b> ничего не нашлось.\n"
    "Проверьте артикул — может, опечатка или лишний символ?"
)
OFFER_EXPIRED = "Этот результат поиска устарел. Найдите деталь заново."
INTERNAL_ERROR = "⚠️ Что-то пошло не так. Попробуйте ещё раз. Ошибка записана в лог."
ADMIN_ONLY = "Оформлять заказ может только ответственный."
CANCELLED = "Ок, отменил."
UNKNOWN_COMMAND = "Не знаю такой команды. Напишите /help — там всё по-простому."
