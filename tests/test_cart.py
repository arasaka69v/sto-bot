"""Тесты корзины."""

from decimal import Decimal

from stobot.core.cart import CartService
from stobot.storage.repositories import CarRepo, CartRepo
from stobot.suppliers.mock import MockSupplier
from tests.conftest import ADMIN, MASTER, run


def offers(article="04465-33471"):
    return run(MockSupplier().search(article))


def make_cart(conn):
    return CartService(CartRepo(conn, CarRepo(conn)))


def test_add_and_total(conn):
    cart = make_cart(conn)
    toyota = offers()[0]  # 38 500, в наличии 6
    cart.add(toyota, MASTER, car_id=None, qty=2)
    items = cart.items()
    assert len(items) == 1
    assert items[0].qty == 2
    assert items[0].added_by_name == "Мастер Ерлан"
    assert cart.total() == Decimal(77000)


def test_same_offer_same_car_is_merged(conn):
    cart = make_cart(conn)
    toyota = offers()[0]
    cart.add(toyota, MASTER, car_id=None)
    result = cart.add(toyota, ADMIN, car_id=None)
    assert result.merged
    assert len(cart.items()) == 1
    assert cart.items()[0].qty == 2


def test_same_offer_different_car_is_separate(conn):
    cars = CarRepo(conn)
    camry = cars.create_or_update("123ABC01", "Камри")
    corolla = cars.create_or_update("777KZ02", "Королла")
    cart = make_cart(conn)
    toyota = offers()[0]
    cart.add(toyota, MASTER, car_id=camry.id)
    cart.add(toyota, MASTER, car_id=corolla.id)
    items = cart.items()
    assert len(items) == 2
    assert {i.car.plate for i in items} == {"123ABC01", "777KZ02"}


def test_qty_limited_by_stock(conn):
    cart = make_cart(conn)
    almaty = offers()[1]  # в наличии 2
    result = cart.add(almaty, MASTER, car_id=None, qty=5)
    assert result.limited_by_stock
    assert result.item.qty == 2


def test_change_qty_and_remove_at_zero(conn):
    cart = make_cart(conn)
    toyota = offers()[0]
    item = cart.add(toyota, MASTER, car_id=None).item
    updated, hint = cart.change_qty(item.id, +1)
    assert updated.qty == 2 and hint is None
    cart.change_qty(item.id, -1)
    removed, hint = cart.change_qty(item.id, -1)
    assert removed is None
    assert hint == "Позиция удалена."
    assert cart.items() == []


def test_cannot_increase_over_stock(conn):
    cart = make_cart(conn)
    almaty = offers()[1]  # 2 шт
    item = cart.add(almaty, MASTER, car_id=None, qty=2).item
    same, hint = cart.change_qty(item.id, +1)
    assert same.qty == 2
    assert "только 2" in hint


def test_remove(conn):
    cart = make_cart(conn)
    item = cart.add(offers()[0], MASTER, car_id=None).item
    assert cart.remove(item.id) is True
    assert cart.remove(item.id) is False  # повторное удаление — не ошибка


def test_fingerprint_changes_when_cart_changes(conn):
    cart = make_cart(conn)
    item = cart.add(offers()[0], MASTER, car_id=None).item
    before = CartService.fingerprint(cart.items())
    cart.change_qty(item.id, +1)
    assert CartService.fingerprint(cart.items()) != before
