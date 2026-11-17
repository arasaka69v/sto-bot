"""Сквозные сценарии через BotApp — как будто мастер пишет в Telegram."""

from tests.conftest import ADMIN, MASTER, STRANGER, find_action, run


def test_stranger_has_no_access(app):
    response = run(app.handle_text(STRANGER, "04465-33471"))
    assert "нет доступа" in response.replies[0].text
    assert str(STRANGER.id) in response.replies[0].text


def test_search_add_to_cart_with_car_and_notify_admin(app):
    run(app.handle_command(MASTER, "car", "Камри 123ABC01"))
    response = run(app.handle_text(MASTER, "04465-33471"))
    text = response.replies[0].text
    assert "TOYOTA" in text and "⭐" in text and "Камри 123ABC01" in text

    added = run(app.handle_action(MASTER, find_action(response, "add:")))
    assert "Камри 123ABC01" in added.replies[0].text
    assert [n.user_id for n in added.notifications] == [ADMIN.id]
    assert app.cart.items()[0].car.plate == "123ABC01"


def test_analogs_button(app):
    response = run(app.handle_text(MASTER, "04465-33471"))
    analogs = run(app.handle_action(MASTER, find_action(response, "an:")))
    text = analogs.replies[0].text
    assert "аналоги" in text and "TRW" in text and "TOYOTA" in text


def test_article_not_found(app):
    response = run(app.handle_text(MASTER, "XX-000-1"))
    assert "ничего не нашлось" in response.replies[0].text


def test_supplier_down_message(app):
    response = run(app.handle_text(MASTER, "OFFLINE-000"))
    assert "не отвечает" in response.replies[0].text


def test_master_cannot_checkout(app):
    response = run(app.handle_action(MASTER, "co"))
    assert "только ответственный" in response.replies[0].text


def test_full_order_flow(app):
    response = run(app.handle_text(MASTER, "90915-YZZE1"))
    run(app.handle_action(MASTER, find_action(response, "add:")))
    cart = run(app.handle_command(ADMIN, "cart"))
    check = run(app.handle_action(ADMIN, find_action(cart, "co")))
    assert "Проверка перед заказом" in check.replies[0].text
    done = run(app.handle_action(ADMIN, find_action(check, "co:ok:")))
    assert "Заказ оформлен" in done.replies[0].text
    assert [n.user_id for n in done.notifications] == [MASTER.id]
    assert app.cart.items() == []
    orders = run(app.handle_command(ADMIN, "orders"))
    assert "MOCK-" in orders.replies[0].text


def test_orders_by_car_text(app):
    run(app.handle_command(MASTER, "car", "Камри 123ABC01"))
    response = run(app.handle_text(MASTER, "04465-33471"))
    run(app.handle_action(MASTER, find_action(response, "add:")))
    check = run(app.handle_action(ADMIN, "co"))
    run(app.handle_action(ADMIN, find_action(check, "co:ok:")))
    history = run(app.handle_text(MASTER, "что заказывали для 123ABC01"))
    assert "Что заказывали для Камри 123ABC01" in history.replies[0].text
    assert "04465-33471" in history.replies[0].text


def test_car_in_plain_text(app):
    response = run(app.handle_text(MASTER, "Камри 123 ABC 01"))
    assert "Камри 123ABC01" in response.replies[0].text
    assert app.state.current_car_id(MASTER.id) is not None


def test_vin_validation(app):
    run(app.handle_command(MASTER, "car", "123ABC01"))
    car = app.cars.find_by_plate("123ABC01")
    run(app.handle_action(MASTER, f"carf:vin:{car.id}"))
    bad = run(app.handle_text(MASTER, "123"))
    assert "17" in bad.replies[0].text
    run(app.handle_text(MASTER, "JTNB11HK103456789"))
    assert app.cars.get(car.id).vin == "JTNB11HK103456789"


def test_rossko_without_docs_gives_clear_error():
    import pytest

    from stobot.suppliers import create_supplier
    from stobot.suppliers.rossko import RosskoNotReady

    with pytest.raises(RosskoNotReady, match="docs/"):
        create_supplier("rossko")
