"""Запуск бота: python main.py"""

from __future__ import annotations

import logging
import sys

from stobot.ai import create_recognizer
from stobot.catalog import create_catalog
from stobot.config import ConfigError, load_settings
from stobot.core.app import BotApp
from stobot.logging_setup import setup_logging
from stobot.storage.db import connect
from stobot.suppliers import create_supplier
from stobot.suppliers.rossko import RosskoNotReady


def main() -> int:
    # 1. Настройки из .env
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"❌ Ошибка в настройках: {e}")
        return 1

    # 2. Логи (секреты автоматически заменяются на ***)
    setup_logging(settings.log_path, settings.secrets)
    log = logging.getLogger("main")

    # 3. Поставщик
    try:
        supplier = create_supplier(settings.supplier)
    except RosskoNotReady as e:
        log.error(str(e))
        print(f"❌ {e}")
        return 1

    # 4. Остальные части
    conn = connect(settings.db_path)
    recognizer = create_recognizer(settings.anthropic_api_key, settings.ai_model)
    app = BotApp(
        conn=conn,
        supplier=supplier,
        recognizer=recognizer,
        catalog=create_catalog(),
        admin_ids=settings.admin_ids,
        test_mode=settings.test_mode,
        normal_delivery_days=settings.normal_delivery_days,
        currency=settings.currency,
    )

    log.info(
        "Бот запускается: поставщик=%s, тестовый режим=%s, ИИ=%s, админов=%d, мастеров=%d",
        settings.supplier,
        settings.test_mode,
        "да" if settings.anthropic_api_key else "нет",
        len(settings.admin_ids),
        len(settings.master_ids),
    )

    # 5. Telegram (импорт здесь, чтобы тесты не требовали Telegram)
    from stobot.adapters.telegram.bot import build_application

    application = build_application(
        settings.telegram_token, app, settings.admin_ids, settings.master_ids
    )
    print("✅ Бот запущен. Остановить: Ctrl+C")
    application.run_polling()
    return 0


if __name__ == "__main__":
    sys.exit(main())
