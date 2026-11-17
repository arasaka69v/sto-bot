"""Клиент реального API Росско (версия 2.1).

Написан строго по официальным описаниям методов (WSDL) из docs/rossko/:
- GetSearch          — поиск по артикулу: цены, склады, сроки, аналоги (crosses);
- GetCheckout        — оформление заказа;
- GetCheckoutDetails — способы доставки и оплаты, адреса (для мастера настройки);
- GetOrders          — заказы (для статусов).

Чего в описании API НЕТ, и мы этого не выдумываем:
- признака «оригинал» — поэтому оригиналы не помечаем, аналоги идут отдельно;
- признака акции/скидки — поэтому 🔥 для Росско не показываем;
- расшифровки кодов статусов — показываем дату доставки, если API её отдаёт.
Поле delivery (целое число) считаем сроком доставки в днях — проверьте
по первому реальному поиску и, если что, скажите.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element

from stobot.config import RosskoConfig
from stobot.core.models import Offer, OrderLine, PlacedOrder
from stobot.suppliers import rossko_soap as soap
from stobot.suppliers.base import OrderRejected, Supplier

log = logging.getLogger(__name__)

# Результат поиска держим минуту: «Показать аналоги» сразу после поиска
# не будет повторно дёргать API
CACHE_SECONDS = 60


class RosskoNotReady(Exception):
    """Росско выбран, но настройки не заполнены."""


def parse_price(raw: str) -> Decimal:
    """'12 345,50' или '12345.50' -> Decimal('12345.50')."""
    cleaned = raw.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal(0)


def _offers_from_part(part: Element) -> list[Offer]:
    """Деталь из ответа GetSearch → по одному предложению на каждый склад."""
    guid = soap.text(part, "guid")
    article = soap.text(part, "partnumber")
    brand = soap.text(part, "brand")
    name = soap.text(part, "name")
    offers = []
    for stock in soap.children(soap.child(part, "stocks"), "stock"):
        stock_id = soap.text(stock, "id")
        offers.append(
            Offer(
                supplier="rossko",
                # guid детали + id склада: по ним находим то же предложение при перепроверке
                offer_id=f"{guid}|{stock_id}",
                article=article,
                brand=brand,
                name=name,
                price=parse_price(soap.text(stock, "price")),
                stock=soap.integer(stock, "count"),
                delivery_days=soap.integer(stock, "delivery"),
                is_original=False,
                promo=None,
                multiplicity=max(soap.integer(stock, "multiplicity", 1), 1),
                note=soap.text(stock, "description") or None,
            )
        )
    return offers


def stock_id_of(offer: Offer) -> str:
    return offer.offer_id.split("|", 1)[1]


class RosskoSupplier(Supplier):
    name = "rossko"
    supports_analogs = True
    supports_order_status = True

    def __init__(self, config: RosskoConfig):
        missing = config.missing_for_search()
        if missing:
            raise RosskoNotReady(
                "Не заполнены настройки Росско: "
                + ", ".join(missing)
                + ". Запустите rossko_setup.bat."
            )
        self.config = config
        self._cache: dict[str, tuple[float, list[Element]]] = {}

    def _auth(self) -> dict:
        return {"KEY1": self.config.key1, "KEY2": self.config.key2}

    async def _search_parts(self, article: str, use_cache: bool = True) -> list[Element]:
        key = article.strip().upper()
        cached = self._cache.get(key)
        if use_cache and cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]
        result = await soap.call(
            "GetSearch",
            {
                **self._auth(),
                "text": article.strip(),
                "delivery_id": self.config.delivery_id,
                "address_id": self.config.address_id,
            },
            "SearchResult",
        )
        if not soap.boolean(result, "success"):
            # Росско так отвечает, когда ничего не нашлось (или на другие отказы)
            log.info("rossko search: %s", soap.text(result, "message"))
            parts: list[Element] = []
        else:
            parts = soap.children(soap.child(result, "PartsList"), "Part")
        self._cache[key] = (time.monotonic(), parts)
        return parts

    async def search(self, article: str) -> list[Offer]:
        parts = await self._search_parts(article)
        return [offer for part in parts for offer in _offers_from_part(part)]

    async def analogs(self, article: str, brand: str) -> list[Offer]:
        parts = await self._search_parts(article)
        result = []
        for part in parts:
            for cross in soap.children(soap.child(part, "crosses"), "Part"):
                result += _offers_from_part(cross)
        return result

    async def refresh_offer(self, offer: Offer) -> Offer | None:
        """Ищем тот же артикул заново (без кэша) и находим тот же склад."""
        parts = await self._search_parts(offer.article, use_cache=False)
        for part in parts:
            group = [part, *soap.children(soap.child(part, "crosses"), "Part")]
            for p in group:
                for fresh in _offers_from_part(p):
                    if fresh.offer_id == offer.offer_id:
                        return fresh
        return None

    async def place_order(self, lines: list[OrderLine], comment: str) -> PlacedOrder:
        missing = self.config.missing_for_order()
        if missing:
            raise OrderRejected(
                "не заполнены настройки заказа: "
                + ", ".join(missing)
                + ". Запустите rossko_setup.bat"
            )
        result = await soap.call(
            "GetCheckout",
            {
                **self._auth(),
                "delivery": {
                    "delivery_id": self.config.delivery_id,
                    "address_id": self.config.address_id,
                },
                "payment": {
                    "payment_id": self.config.payment_id,
                    "requisite_id": self.config.requisite_id,
                },
                "contact": {
                    "name": self.config.contact_name,
                    "phone": self.config.contact_phone,
                    "comment": comment,
                },
                "delivery_parts": self.config.delivery_parts,
                "PARTS": {
                    "Part": [
                        {
                            "partnumber": line.offer.article,
                            "brand": line.offer.brand,
                            "stock": stock_id_of(line.offer),
                            "count": line.qty,
                        }
                        for line in lines
                    ]
                },
            },
            "CheckoutResult",
        )
        message = soap.text(result, "message")
        if not soap.boolean(result, "success"):
            raise OrderRejected(message or "Росско не принял заказ, причина не указана")

        order_ids = [
            el.text.strip() for el in soap.children(soap.child(result, "OrderIDS"), "id") if el.text
        ]
        rejected = tuple(
            (soap.text(e, "brand"), soap.text(e, "partnumber"), soap.text(e, "message"))
            for e in soap.children(soap.child(result, "ItemsErrorList"), "ItemError")
        )
        if not order_ids:
            reasons = "; ".join(r[2] for r in rejected) or message
            raise OrderRejected(reasons or "Росско не вернул номер заказа")
        log.info("rossko order ids=%s rejected=%d", order_ids, len(rejected))
        return PlacedOrder(
            supplier_order_id=", ".join(order_ids), status="Принят", rejected=rejected
        )

    async def order_statuses(self, supplier_order_ids: list[str]) -> dict[str, str]:
        """Для каждого нашего заказа — дата доставки, если Росско её уже назначил."""
        numbers: dict[str, list[int]] = {}
        for combined in supplier_order_ids:
            numbers[combined] = [int(x) for x in combined.split(",") if x.strip().isdigit()]
        all_ids = sorted({n for ids in numbers.values() for n in ids})[:20]  # лимит API — 20
        if not all_ids:
            return {}
        result = await soap.call(
            "GetOrders", {**self._auth(), "order_ids": {"id": all_ids}}, "OrdersResult"
        )
        dates: dict[int, str] = {}
        for order in soap.children(soap.child(result, "OrdersList"), "Order"):
            date = soap.text(order, "delivery_date")
            if date:
                dates[soap.integer(order, "id")] = date
        statuses = {}
        for combined, ids in numbers.items():
            known = sorted({dates[i] for i in ids if i in dates})
            if known:
                statuses[combined] = "Доставка: " + ", ".join(known)
        return statuses

    async def verify(self) -> None:
        """Проверка ключей при запуске бота: понятная ошибка сразу, а не у мастера."""
        await soap.call("GetCheckoutDetails", self._auth(), "CheckoutDetailsResult")


def create_rossko_supplier(config: RosskoConfig) -> RosskoSupplier:
    return RosskoSupplier(config)
