"""Машина по VIN и поиск по названию — без каталога и с каталогом."""

import sqlite3

from stobot.catalog.base import VinCatalog
from stobot.core.search import looks_like_article
from stobot.core.vin import is_vin, make_from_vin
from stobot.storage.db import connect
from tests.conftest import ADMIN, MASTER, find_action, make_app, run

VIN = "JTNB11HK103456789"


class FakeCatalog(VinCatalog):
    """Каталог для тестов: передние колодки находит, остальное — нет."""

    def __init__(self):
        self.calls = []

    def is_available(self) -> bool:
        return True

    async def find_articles(self, part_key, answers, car):
        self.calls.append((part_key, dict(answers), car.vin if car else None))
        if part_key == "brake_pads" and answers.get("axle") == "front":
            return ["04465-33471"]
        return []


def app_with_catalog(conn):
    app = make_app(conn)
    app.catalog = FakeCatalog()
    return app


# --- Распознавание VIN ---


def test_is_vin():
    assert is_vin(VIN)
    assert is_vin("jtnb 11hk1034 56789")
    assert not is_vin("JTNB11HK10345678")  # 16 символов
    assert not is_vin("JTNB11HK1O3456789")  # буква O в VIN не бывает
    assert not is_vin("04465-33471")


def test_vin_is_not_treated_as_article_first(app):
    # VIN похож и на артикул — но бот должен выбрать машину, а не искать деталь
    assert looks_like_article(VIN)
    response = run(app.handle_text(MASTER, VIN))
    assert "Машина выбрана по VIN" in response.replies[0].text


def test_make_from_vin():
    assert make_from_vin(VIN) == "Toyota"
    assert make_from_vin("JTHBA30G455012345") == "Lexus"
    assert make_from_vin("KMHDN41BP4U123456") == "Hyundai"
    assert make_from_vin("ZZZ11111111111111") is None  # незнакомый — не угадываем


# --- Выбор машины ---


def test_vin_selects_car_without_any_questions(app):
    response = run(app.handle_text(MASTER, VIN))
    text = response.replies[0].text
    assert "Toyota" in text and VIN in text
    car = app.cars.find_by_vin(VIN)
    assert car.plate is None and car.model == "Toyota"
    assert app.state.current_car_id(MASTER.id) == car.id
    # Тот же VIN второй раз — та же машина, без дублей
    run(app.handle_text(ADMIN, VIN))
    assert app.state.current_car_id(ADMIN.id) == car.id


def test_cart_and_orders_by_vin(app):
    run(app.handle_text(MASTER, VIN))
    found = run(app.handle_text(MASTER, "90915-YZZE1"))
    added = run(app.handle_action(MASTER, find_action(found, "add:")))
    assert "Toyota VIN …456789" in added.replies[0].text
    check = run(app.handle_action(ADMIN, "co"))
    run(app.handle_action(ADMIN, find_action(check, "co:ok:")))
    history = run(app.handle_text(MASTER, f"что заказывали для {VIN}"))
    assert "90915-YZZE1" in history.replies[0].text


def test_plate_without_model_is_allowed(app):
    response = run(app.handle_command(MASTER, "car", "123ABC01"))
    assert "123ABC01" in response.replies[0].text
    assert app.cars.find_by_plate("123ABC01") is not None


# --- Поиск по названию без каталога: никаких вопросов ---


def test_no_catalog_no_questions(app):
    run(app.handle_text(MASTER, VIN))
    response = run(app.handle_text(MASTER, "граната"))
    reply = response.replies[0]
    assert "ШРУС" in reply.text and "артикул" in reply.text
    assert reply.buttons == []  # ничего не спрашивает
    assert app.state.pending(MASTER.id) is None


# --- С каталогом ---


def test_catalog_with_vin_finds_offers_directly(conn):
    app = app_with_catalog(conn)
    run(app.handle_text(MASTER, VIN))
    response = run(app.handle_text(MASTER, "калодки перед"))
    # Ось известна из текста, двигатель — из VIN: сразу цены, без вопросов
    assert "04465-33471" in response.replies[0].text
    assert find_action(response, "add:")
    assert app.catalog.calls == [("brake_pads", {"axle": "front"}, VIN)]


def test_catalog_without_vin_asks_vin_then_continues(conn):
    app = app_with_catalog(conn)
    asked = run(app.handle_text(MASTER, "калодки перед"))
    assert "VIN" in asked.replies[0].text
    result = run(app.handle_text(MASTER, VIN))
    texts_ = [r.text for r in result.replies]
    assert "Машина выбрана по VIN" in texts_[0]
    assert "04465-33471" in texts_[1]  # поиск продолжился сам


def test_catalog_asks_only_what_vin_does_not_know(conn):
    app = app_with_catalog(conn)
    run(app.handle_text(MASTER, VIN))
    # Опора двигателя: вопрос про КПП знает каталог по VIN — спрашиваем только какая опора
    response = run(app.handle_text(MASTER, "подушка двигателя"))
    text = response.replies[0].text
    assert "Какая опора" in text and "КПП" not in text
    # Масляный фильтр: двигатель знает каталог — вопросов нет вообще
    response = run(app.handle_text(MASTER, "масляный фильтр"))
    assert response.replies[0].buttons == []
    assert "не нашёл" in response.replies[0].text


def test_catalog_clarify_buttons_then_search(conn):
    app = app_with_catalog(conn)
    run(app.handle_text(MASTER, VIN))
    asked = run(app.handle_text(MASTER, "колодки"))
    assert "Ось" in asked.replies[0].text
    session = find_action(asked, "cl:").split(":")[1]
    found = run(app.handle_action(MASTER, f"cl:{session}:axle:front"))
    assert "04465-33471" in found.replies[0].text


# --- Обновление старой базы ---


def test_old_database_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE cars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT NOT NULL UNIQUE,
            model TEXT NOT NULL DEFAULT '',
            vin TEXT, engine TEXT, year INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO cars (plate, model, engine) VALUES ('123ABC01', 'Камри', '2AR-FE');
        """
    )
    old.commit()
    old.close()

    conn = connect(path)
    columns = {c["name"]: c for c in conn.execute("PRAGMA table_info(cars)")}
    assert columns["plate"]["notnull"] == 0
    row = conn.execute("SELECT * FROM cars").fetchone()
    assert (row["plate"], row["model"], row["engine"]) == ("123ABC01", "Камри", "2AR-FE")
    conn.execute("INSERT INTO cars (vin) VALUES (?)", (VIN,))  # теперь можно без номера
    conn.close()
    connect(path).close()  # повторный запуск не ломает базу
