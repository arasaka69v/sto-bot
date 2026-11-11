"""Общая корзина: добавить, изменить количество, удалить, посчитать итог."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from stobot.core.models import CartItem, Offer, User
from stobot.storage.repositories import CartRepo


@dataclass
class AddResult:
    item: CartItem
    merged: bool  # True — такая позиция уже была, просто увеличили количество
    limited_by_stock: bool  # True — хотели больше, чем есть на складе


class CartService:
    def __init__(self, repo: CartRepo):
        self.repo = repo

    def items(self) -> list[CartItem]:
        return self.repo.all()

    def total(self, items: list[CartItem] | None = None) -> Decimal:
        items = self.items() if items is None else items
        return sum((i.total for i in items), Decimal(0))

    def add(self, offer: Offer, user: User, car_id: int | None, qty: int = 1) -> AddResult:
        """Добавляет позицию. Если та же деталь для той же машины уже есть — +qty.

        Количество не может быть больше, чем есть на складе (если склад известен).
        """
        existing = self.repo.find_same(offer, car_id)
        wanted = (existing.qty if existing else 0) + qty
        allowed = min(wanted, offer.stock) if offer.stock > 0 else wanted
        limited = allowed < wanted

        if existing:
            self.repo.set_qty(existing.id, allowed)
            item_id = existing.id
        else:
            item_id = self.repo.add(offer, allowed, user.id, user.name, car_id)
        item = self.repo.get(item_id)
        assert item is not None
        return AddResult(item=item, merged=existing is not None, limited_by_stock=limited)

    def change_qty(self, item_id: int, delta: int) -> tuple[CartItem | None, str | None]:
        """Меняет количество на delta (+1 / -1).

        Возвращает (позиция или None если удалена, подсказка для мастера или None).
        Количество 0 — позиция удаляется.
        """
        item = self.repo.get(item_id)
        if item is None:
            return None, "Этой позиции уже нет в корзине."
        new_qty = item.qty + delta
        if new_qty <= 0:
            self.repo.remove(item_id)
            return None, "Позиция удалена."
        if item.offer.stock > 0 and new_qty > item.offer.stock:
            return item, f"На складе только {item.offer.stock} шт."
        self.repo.set_qty(item_id, new_qty)
        return self.repo.get(item_id), None

    def remove(self, item_id: int) -> bool:
        if self.repo.get(item_id) is None:
            return False
        self.repo.remove(item_id)
        return True

    def remove_many(self, item_ids: list[int]) -> None:
        self.repo.remove_many(item_ids)

    @staticmethod
    def fingerprint(items: list[CartItem]) -> str:
        """«Отпечаток» корзины: если кто-то поменял корзину после проверки,
        отпечаток изменится, и заказ по старой проверке не уйдёт."""
        raw = ";".join(f"{i.id}:{i.qty}" for i in sorted(items, key=lambda i: i.id))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
