"""Клиент реального API Росско.

ПОКА НЕ РЕАЛИЗОВАН. Методы, поля и параметры API нельзя придумывать —
клиент будет написан строго по документации, которую нужно положить в docs/.
До этого используйте SUPPLIER=mock.

Что здесь появится (по документации):
- search / analogs — поиск по артикулу и аналоги (если API их отдаёт);
- refresh_offer — повторная проверка цены и наличия;
- place_order — отправка заказа с параметрами аккаунта из .env;
- order_statuses — статусы заказов (если API их отдаёт).
"""

from __future__ import annotations

from stobot.suppliers.base import Supplier


class RosskoNotReady(Exception):
    pass


def create_rossko_supplier() -> Supplier:
    """Здесь будет создаваться настоящий клиент RosskoSupplier(Supplier)."""
    raise RosskoNotReady(
        "Клиент Росско ещё не написан: нужна документация API в папке docs/. "
        "Пока поставьте SUPPLIER=mock в .env."
    )
