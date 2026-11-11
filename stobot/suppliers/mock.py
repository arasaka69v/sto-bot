"""Mock-поставщик: правдоподобные тестовые данные вместо реального API.

Нужен, чтобы проверить бота целиком, пока нет ключей Росско.
Включается в .env: SUPPLIER=mock
"""

from __future__ import annotations

import logging
import re
import time
from decimal import Decimal

from stobot.core.models import Offer, OrderLine, PlacedOrder
from stobot.suppliers import mock_data
from stobot.suppliers.base import Supplier, SupplierUnavailable

log = logging.getLogger(__name__)


def normalize_article(article: str) -> str:
    """'04465-33471 ' -> '0446533471': убираем пробелы, дефисы, точки."""
    return re.sub(r"[^0-9A-ZА-Я]", "", article.upper())


def _make_offers(rows: list[tuple], seen_ids: set[str]) -> list[Offer]:
    offers = []
    for article, brand, name, price, stock, days, original, promo in rows:
        offer_id = f"{brand}-{normalize_article(article)}"
        # Одинаковая деталь с разных складов — делаем id уникальным
        suffix = 2
        base_id = offer_id
        while offer_id in seen_ids:
            offer_id = f"{base_id}-{suffix}"
            suffix += 1
        seen_ids.add(offer_id)
        offers.append(
            Offer(
                supplier="mock",
                offer_id=offer_id,
                article=article,
                brand=brand,
                name=name,
                price=Decimal(price),
                stock=stock,
                delivery_days=days,
                is_original=original,
                promo=promo,
            )
        )
    return offers


class MockSupplier(Supplier):
    name = "mock"
    supports_analogs = True
    supports_order_status = True

    def __init__(self) -> None:
        seen: set[str] = set()
        # Собираем все предложения один раз при старте
        self._parts = {k: _make_offers(v, seen) for k, v in mock_data.PARTS.items()}
        self._analogs = {k: _make_offers(v, seen) for k, v in mock_data.ANALOGS.items()}
        self._by_id: dict[str, Offer] = {}
        for group in (*self._parts.values(), *self._analogs.values()):
            for offer in group:
                self._by_id[offer.offer_id] = offer

    def _check_online(self, article: str) -> None:
        if normalize_article(article) == mock_data.OFFLINE_ARTICLE:
            raise SupplierUnavailable("mock: имитация недоступности API")

    async def search(self, article: str) -> list[Offer]:
        self._check_online(article)
        key = normalize_article(article)
        log.info("mock search article=%s", key)
        if key in self._parts:
            return list(self._parts[key])
        # Мастер мог ввести артикул аналога — ищем и среди них
        return [o for o in self._by_id.values() if normalize_article(o.article) == key]

    async def analogs(self, article: str, brand: str) -> list[Offer]:
        self._check_online(article)
        key = normalize_article(article)
        if key in self._analogs:
            return list(self._analogs[key])
        # Это артикул аналога: отдаём оригинал и остальные аналоги
        for original_key, group in self._analogs.items():
            if any(normalize_article(o.article) == key for o in group):
                others = [o for o in group if normalize_article(o.article) != key]
                return self._parts.get(original_key, []) + others
        return []

    async def refresh_offer(self, offer: Offer) -> Offer | None:
        current = self._by_id.get(offer.offer_id)
        if current is None:
            return None
        changes = {}
        if offer.offer_id in mock_data.RECHECK_PRICE_CHANGES:
            changes["price"] = Decimal(mock_data.RECHECK_PRICE_CHANGES[offer.offer_id])
        if offer.offer_id in mock_data.RECHECK_STOCK_CHANGES:
            changes["stock"] = mock_data.RECHECK_STOCK_CHANGES[offer.offer_id]
        if not changes:
            return current
        data = current.to_dict() | {k: str(v) if k == "price" else v for k, v in changes.items()}
        return Offer.from_dict(data)

    async def place_order(self, lines: list[OrderLine], comment: str) -> PlacedOrder:
        # Номер с временем создания — по нему mock «двигает» статус заказа
        order_id = f"MOCK-{int(time.time())}"
        log.info("mock place_order id=%s lines=%d", order_id, len(lines))
        return PlacedOrder(supplier_order_id=order_id, status="Принят")

    async def order_statuses(self, supplier_order_ids: list[str]) -> dict[str, str]:
        result = {}
        now = time.time()
        for order_id in supplier_order_ids:
            try:
                created = int(order_id.split("-")[1])
            except (IndexError, ValueError):
                continue
            minutes = (now - created) / 60
            if minutes < 2:
                result[order_id] = "Принят"
            elif minutes < 10:
                result[order_id] = "Собирается на складе"
            else:
                result[order_id] = "Передан в доставку"
        return result
