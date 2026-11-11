"""Тесты оформления заказа: перепроверка, подтверждение, тестовый режим."""

from decimal import Decimal

from stobot.core.checkout import compare
from stobot.core.models import CheckStatus
from stobot.suppliers.base import SupplierUnavailable
from tests.conftest import ADMIN, MASTER, run


def search(app, article):
    return run(app.supplier.search(article))


def analogs(app, article):
    return run(app.supplier.analogs(article, ""))


def by_brand(offers, brand):
    return next(o for o in offers if o.brand == brand)


def test_compare_statuses():
    from stobot.suppliers.mock import MockSupplier

    offer = run(MockSupplier().search("04465-33471"))[0]
    assert compare(offer, 1, offer) == CheckStatus.OK
    assert compare(offer, 1, None) == CheckStatus.OUT_OF_STOCK
    cheaper = type(offer)(**{**offer.__dict__, "price": Decimal(1)})
    assert compare(offer, 1, cheaper) == CheckStatus.PRICE_CHANGED
    assert compare(offer, 100, offer) == CheckStatus.NOT_ENOUGH


def test_recheck_finds_changes(app):
    pads = analogs(app, "04465-33471")
    filters = analogs(app, "90915-YZZE1")
    app.cart.add(by_brand(pads, "TRW"), MASTER, None)  # подорожает
    app.cart.add(by_brand(filters, "VIC"), MASTER, None)  # закончится
    app.cart.add(by_brand(pads, "NIBK"), MASTER, None, qty=3)  # останется 1 шт
    app.cart.add(by_brand(pads, "BREMBO"), MASTER, None)  # без изменений

    report = run(app.checkout.check(ADMIN))
    statuses = {c.item.offer.brand: c.status for c in report.checks}
    assert statuses == {
        "TRW": CheckStatus.PRICE_CHANGED,
        "VIC": CheckStatus.OUT_OF_STOCK,
        "NIBK": CheckStatus.NOT_ENOUGH,
        "BREMBO": CheckStatus.OK,
    }
    assert report.has_changes
    # TRW по новой цене 23 500 + NIBK 1 шт × 14 500 + BREMBO 27 400
    assert report.total == Decimal(23500 + 14500 + 27400)


def test_confirm_sends_order_and_cleans_cart(app):
    pads = analogs(app, "04465-33471")
    filters = analogs(app, "90915-YZZE1")
    app.cart.add(by_brand(pads, "BREMBO"), MASTER, None, qty=2)
    app.cart.add(by_brand(filters, "VIC"), MASTER, None)  # закончится — останется в корзине

    report = run(app.checkout.check(ADMIN))
    result = run(app.checkout.confirm(report.session_id, ADMIN))
    assert result.ok and result.message_key == "sent"
    assert result.placed.supplier_order_id.startswith("MOCK-")
    assert result.total == Decimal(27400 * 2)
    remaining = app.cart.items()
    assert [i.offer.brand for i in remaining] == ["VIC"]
    orders = app.orders.recent()
    assert len(orders) == 1 and orders[0].lines[0]["qty"] == 2


def test_double_confirm_does_not_order_twice(app):
    app.cart.add(search(app, "90915-YZZE1")[0], MASTER, None)
    report = run(app.checkout.check(ADMIN))
    first = run(app.checkout.confirm(report.session_id, ADMIN))
    second = run(app.checkout.confirm(report.session_id, ADMIN))
    assert first.message_key == "sent"
    assert second.ok is False
    assert len(app.orders.recent()) == 1


def test_cart_changed_after_check_blocks_order(app):
    item = app.cart.add(search(app, "90915-YZZE1")[0], MASTER, None).item
    report = run(app.checkout.check(ADMIN))
    app.cart.change_qty(item.id, +1)  # мастер поменял корзину, пока админ смотрел
    result = run(app.checkout.confirm(report.session_id, ADMIN))
    assert result.message_key == "cart_changed"
    assert app.orders.recent() == []


def test_test_mode_sends_nothing(test_mode_app):
    app = test_mode_app
    app.cart.add(search(app, "90915-YZZE1")[0], MASTER, None)
    report = run(app.checkout.check(ADMIN))
    result = run(app.checkout.confirm(report.session_id, ADMIN))
    assert result.message_key == "test_mode"
    assert len(result.lines) == 1
    assert len(app.cart.items()) == 1  # корзина не тронута
    assert app.orders.recent() == []  # заказ не сохранён


def test_all_out_of_stock_nothing_to_order(app):
    app.cart.add(by_brand(analogs(app, "90915-YZZE1"), "VIC"), MASTER, None)
    report = run(app.checkout.check(ADMIN))
    assert report.to_order == []
    result = run(app.checkout.confirm(report.session_id, ADMIN))
    assert result.message_key == "empty"


def test_supplier_down_on_order_allows_retry(app, monkeypatch):
    app.cart.add(search(app, "90915-YZZE1")[0], MASTER, None)
    report = run(app.checkout.check(ADMIN))

    async def broken(*args, **kwargs):
        raise SupplierUnavailable("нет связи")

    original = app.supplier.place_order
    monkeypatch.setattr(app.supplier, "place_order", broken)
    try:
        run(app.checkout.confirm(report.session_id, ADMIN))
    except SupplierUnavailable:
        pass
    assert len(app.cart.items()) == 1  # корзина цела
    monkeypatch.setattr(app.supplier, "place_order", original)
    result = run(app.checkout.confirm(report.session_id, ADMIN))
    assert result.message_key == "sent"


def test_empty_cart_check_returns_none(app):
    assert run(app.checkout.check(ADMIN)) is None
