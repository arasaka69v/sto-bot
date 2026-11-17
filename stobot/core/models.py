"""Основные объекты бота. Они не зависят ни от Telegram, ни от Росско."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import StrEnum


@dataclass(frozen=True)
class User:
    """Тот, кто пишет боту. id — Telegram ID (позже может быть номер WhatsApp)."""

    id: int
    name: str
    is_admin: bool = False
    is_master: bool = False


@dataclass(frozen=True)
class Offer:
    """Одно предложение поставщика: конкретная деталь по конкретной цене.

    Цены храним в Decimal, а не float: float иногда даёт 0.1 + 0.2 = 0.30000000000000004,
    а с деньгами так нельзя.
    """

    supplier: str  # "mock", "rossko"
    offer_id: str  # идентификатор предложения у поставщика (нужен для заказа)
    article: str
    brand: str
    name: str
    price: Decimal
    stock: int  # сколько штук в наличии
    delivery_days: int
    is_original: bool = False
    promo: str | None = None  # текст акции — ТОЛЬКО если его вернул поставщик

    def to_dict(self) -> dict:
        data = asdict(self)
        data["price"] = str(self.price)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Offer:
        data = dict(data)
        data["price"] = Decimal(data["price"])
        return cls(**data)


def car_title(model: str | None, plate: str | None, vin: str | None) -> str:
    """Как машина называется в сообщениях: «Toyota 123ABC01» или «Toyota VIN …456789»."""
    parts = [model] if model else []
    if plate:
        parts.append(plate)
    elif vin:
        parts.append(f"VIN …{vin[-6:]}")
    return " ".join(parts) or "машина"


@dataclass(frozen=True)
class Car:
    id: int
    vin: str | None = None  # главное: по VIN каталог подберёт детали
    plate: str | None = None  # госномер, например 123ABC01 (необязательно)
    model: str = ""  # «Toyota» (определили по VIN) или то, что указал мастер
    engine: str | None = None
    year: int | None = None

    @property
    def title(self) -> str:
        return car_title(self.model, self.plate, self.vin)


@dataclass(frozen=True)
class CartItem:
    id: int
    offer: Offer
    qty: int
    added_by_id: int
    added_by_name: str
    car: Car | None = None

    @property
    def total(self) -> Decimal:
        return self.offer.price * self.qty


class CheckStatus(StrEnum):
    """Что показала повторная проверка позиции перед заказом."""

    OK = "ok"
    PRICE_CHANGED = "price_changed"
    NOT_ENOUGH = "not_enough"  # есть, но меньше, чем нужно
    OUT_OF_STOCK = "out_of_stock"


@dataclass
class ItemCheck:
    item: CartItem
    status: CheckStatus
    current: Offer | None  # актуальное предложение (None — позиции больше нет)

    @property
    def order_qty(self) -> int:
        """Сколько штук реально закажем."""
        if self.current is None or self.status == CheckStatus.OUT_OF_STOCK:
            return 0
        return min(self.item.qty, self.current.stock)

    @property
    def will_order(self) -> bool:
        return self.order_qty > 0


@dataclass(frozen=True)
class OrderLine:
    """Строка заказа, которая уходит поставщику."""

    offer: Offer
    qty: int
    car_id: int | None = None
    added_by_id: int | None = None


@dataclass(frozen=True)
class PlacedOrder:
    """Ответ поставщика на заказ."""

    supplier_order_id: str
    status: str


@dataclass
class Order:
    id: int
    supplier: str
    supplier_order_id: str
    status: str
    total: Decimal
    created_at: str
    lines: list[dict] = field(default_factory=list)
