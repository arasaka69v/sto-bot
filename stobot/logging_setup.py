"""Настройка логов: пишем в файл и в консоль, секреты заменяем на ***."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class SecretFilter(logging.Filter):
    """Вырезает секреты (токены, ключи) из любого сообщения лога.

    Зачем: библиотека для Telegram пишет в лог адреса запросов,
    а в них есть токен бота. Фильтр заменяет его на ***.
    """

    def __init__(self, secrets: tuple[str, ...]):
        super().__init__()
        self.secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.secrets:
            return True
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "***")
        # Сохраняем уже «очищенный» текст, чтобы аргументы не подставились заново
        record.msg = message
        record.args = None
        return True


def setup_logging(log_path: Path, secrets: tuple[str, ...]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    secret_filter = SecretFilter(secrets)

    # Файл до 5 МБ, храним 5 старых копий — диск не переполнится
    file_handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    console = logging.StreamHandler()
    for handler in (file_handler, console):
        handler.setFormatter(fmt)
        handler.addFilter(secret_filter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [file_handler, console]

    # httpx пишет каждый запрос к Telegram (с токеном в адресе) — оставим только предупреждения
    logging.getLogger("httpx").setLevel(logging.WARNING)
