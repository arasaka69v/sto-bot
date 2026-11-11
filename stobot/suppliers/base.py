"""Общий интерфейс поставщика запчастей.

Бот работает только с этим интерфейсом и не знает, кто стоит за ним:
Росско, тестовые данные или новый поставщик в будущем. Чтобы добавить
поставщика, достаточно написать новый класс с этими же методами.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from stobot.core.models import Offer, OrderLine, PlacedOrder


class SupplierError(Exception):
    """Базовая ошибка поставщика."""


class SupplierUnavailable(SupplierError):
    """Поставщик не отвечает (нет интернета, сервер упал, таймаут)."""


class OrderRejected(SupplierError):
    """Поставщик отказался принять заказ. В тексте — причина от поставщика."""


class Supplier(ABC):
    #: короткое имя: "mock", "rossko"
    name: str = ""
    #: умеет ли поставщик искать аналоги
    supports_analogs: bool = False
    #: отдаёт ли поставщик статусы заказов
    supports_order_status: bool = False

    @abstractmethod
    async def search(self, article: str) -> list[Offer]:
        """Предложения по артикулу. Пустой список — ничего не найдено."""

    async def analogs(self, article: str, brand: str) -> list[Offer]:
        """Аналоги (заменители) детали. По умолчанию — не поддерживается."""
        return []

    @abstractmethod
    async def refresh_offer(self, offer: Offer) -> Offer | None:
        """Актуальная цена и наличие того же предложения. None — больше не продаётся."""

    @abstractmethod
    async def place_order(self, lines: list[OrderLine], comment: str) -> PlacedOrder:
        """Отправить заказ. Параметры аккаунта (склад, адрес, оплата) — из .env."""

    async def order_statuses(self, supplier_order_ids: list[str]) -> dict[str, str]:
        """Статусы заказов {номер: статус}. По умолчанию — не поддерживается."""
        return {}
