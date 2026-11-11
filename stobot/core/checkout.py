"""Оформление заказа: повторная проверка → подтверждение админом → отправка.

Почему проверяем заново: между «добавил в корзину» и «заказал» могут пройти
часы — цена изменится или деталь закончится. Админ должен видеть это ДО заказа.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal

from stobot.core.cart import CartService
from stobot.core.models import CheckStatus, ItemCheck, Offer, OrderLine, PlacedOrder, User
from stobot.storage.repositories import JsonSessionRepo, OrderRepo
from stobot.suppliers.base import Supplier

log = logging.getLogger(__name__)


@dataclass
class CheckReport:
    session_id: int
    checks: list[ItemCheck]

    @property
    def to_order(self) -> list[ItemCheck]:
        return [c for c in self.checks if c.will_order]

    @property
    def has_changes(self) -> bool:
        return any(c.status != CheckStatus.OK for c in self.checks)

    @property
    def total(self) -> Decimal:
        return sum((c.current.price * c.order_qty for c in self.to_order if c.current), Decimal(0))


@dataclass
class ConfirmResult:
    ok: bool
    message_key: str  # "sent", "test_mode", "cart_changed", "expired", "already_used", "empty"
    placed: PlacedOrder | None = None
    lines: list[OrderLine] = field(default_factory=list)
    total: Decimal = Decimal(0)
    order_id: int | None = None
    skipped: list[ItemCheck] = field(default_factory=list)  # что не заказали (нет в наличии)


def compare(item_offer: Offer, qty: int, current: Offer | None) -> CheckStatus:
    """Сравнивает то, что в корзине, с тем, что сейчас у поставщика."""
    if current is None or current.stock <= 0:
        return CheckStatus.OUT_OF_STOCK
    if current.stock < qty:
        return CheckStatus.NOT_ENOUGH
    if current.price != item_offer.price:
        return CheckStatus.PRICE_CHANGED
    return CheckStatus.OK


class CheckoutService:
    def __init__(
        self,
        supplier: Supplier,
        cart: CartService,
        sessions: JsonSessionRepo,
        orders: OrderRepo,
        test_mode: bool,
    ):
        self.supplier = supplier
        self.cart = cart
        self.sessions = sessions
        self.orders = orders
        self.test_mode = test_mode

    async def check(self, admin: User) -> CheckReport | None:
        """Перепроверяет каждую позицию. None — корзина пуста.

        Может выбросить SupplierUnavailable — тогда ничего не сохраняем.
        """
        items = self.cart.items()
        if not items:
            return None
        checks = []
        for item in items:
            current = await self.supplier.refresh_offer(item.offer)
            status = compare(item.offer, item.qty, current)
            checks.append(ItemCheck(item=item, status=status, current=current))
            log.info(
                "recheck item=%s offer=%s status=%s", item.id, item.offer.offer_id, status.value
            )

        data = {
            "checks": [
                {
                    "item_id": c.item.id,
                    "status": c.status.value,
                    "current": c.current.to_dict() if c.current else None,
                }
                for c in checks
            ]
        }
        session_id = self.sessions.create_checkout(admin.id, CartService.fingerprint(items), data)
        return CheckReport(session_id=session_id, checks=checks)

    def _load_checks(self, data: dict) -> list[ItemCheck] | None:
        checks = []
        for row in data["checks"]:
            item = self.cart.repo.get(row["item_id"])
            if item is None:
                return None
            current = Offer.from_dict(row["current"]) if row["current"] else None
            checks.append(ItemCheck(item=item, status=CheckStatus(row["status"]), current=current))
        return checks

    async def confirm(self, session_id: int, admin: User) -> ConfirmResult:
        """Админ нажал «Подтвердить». Отправляем ровно то, что он видел на экране."""
        row = self.sessions.get_checkout(session_id)
        if row is None or row["expired"]:
            return ConfirmResult(ok=False, message_key="expired")
        if row["used"]:
            return ConfirmResult(ok=False, message_key="already_used")
        # Корзину могли поменять после проверки — тогда админ видел устаревшие данные
        if CartService.fingerprint(self.cart.items()) != row["cart_fingerprint"]:
            return ConfirmResult(ok=False, message_key="cart_changed")
        checks = self._load_checks(json.loads(row["data_json"]))
        if checks is None:
            return ConfirmResult(ok=False, message_key="cart_changed")

        to_order = [c for c in checks if c.will_order]
        skipped = [c for c in checks if not c.will_order]
        if not to_order:
            return ConfirmResult(ok=False, message_key="empty", skipped=skipped)

        lines = [
            OrderLine(
                offer=c.current,
                qty=c.order_qty,  # type: ignore[arg-type]
                car_id=c.item.car.id if c.item.car else None,
                added_by_id=c.item.added_by_id,
            )
            for c in to_order
        ]
        total = sum((ln.offer.price * ln.qty for ln in lines), Decimal(0))

        if self.test_mode:
            # Ничего не отправляем и корзину не трогаем — только показываем
            log.info("TEST_MODE: order NOT sent, lines=%d total=%s", len(lines), total)
            return ConfirmResult(
                ok=True, message_key="test_mode", lines=lines, total=total, skipped=skipped
            )

        # Помечаем заранее: второе нажатие «Подтвердить» не отправит заказ дважды
        if not self.sessions.mark_checkout_used(session_id):
            return ConfirmResult(ok=False, message_key="already_used")

        comment = f"Заказ из Telegram-бота, подтвердил {admin.name}"
        try:
            placed = await self.supplier.place_order(lines, comment)
        except Exception:
            # Заказ не ушёл — разрешаем попробовать снова
            self.sessions.unmark_checkout(session_id)
            raise

        order_id = self.orders.save(self.supplier.name, placed, lines, total, admin.id)
        # Из корзины убираем только то, что заказали. То, чего нет в наличии, остаётся.
        self.cart.remove_many([c.item.id for c in to_order])
        log.info(
            "ORDER sent: local_id=%s supplier_id=%s total=%s lines=%d",
            order_id,
            placed.supplier_order_id,
            total,
            len(lines),
        )
        return ConfirmResult(
            ok=True,
            message_key="sent",
            placed=placed,
            lines=lines,
            total=total,
            order_id=order_id,
            skipped=skipped,
        )
