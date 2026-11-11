"""Ответы бота в виде, не зависящем от мессенджера.

Логика бота возвращает Reply: текст + кнопки. А как это нарисовать
(Telegram inline-кнопки, WhatsApp-кнопки или список) — решает адаптер.
Так при переходе на WhatsApp меняется только адаптер.

Разметка текста: только <b>жирный</b> и <i>курсив</i>. Telegram понимает
это как HTML, а WhatsApp-адаптер заменит на *жирный* и _курсив_.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Button:
    text: str
    action: str  # короткая команда, например "add:15" (до 64 байт — ограничение Telegram)


@dataclass
class Reply:
    text: str
    buttons: list[list[Button]] = field(default_factory=list)  # ряды кнопок
    edit: bool = False  # True — заменить сообщение, на котором нажали кнопку


@dataclass
class Notification:
    """Сообщение другому пользователю (например, админу: «в корзине новая позиция»)."""

    user_id: int
    reply: Reply


@dataclass
class Response:
    replies: list[Reply] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)
    popup: str | None = None  # короткая всплывающая подсказка при нажатии кнопки

    @classmethod
    def text(
        cls, text: str, buttons: list[list[Button]] | None = None, edit: bool = False
    ) -> Response:
        return cls(replies=[Reply(text, buttons or [], edit)])
