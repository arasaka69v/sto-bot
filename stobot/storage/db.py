"""База данных SQLite: создание таблиц и подключение.

SQLite — это один файл (data/sto_bot.db), отдельный сервер не нужен.
Для 2–4 мастеров этого с запасом хватает, и легко переносится на VPS.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
-- Машины клиентов
CREATE TABLE IF NOT EXISTS cars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate TEXT NOT NULL UNIQUE,          -- госномер без пробелов, заглавными
    model TEXT NOT NULL DEFAULT '',
    vin TEXT,
    engine TEXT,
    year INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Ответы на уточняющие вопросы, которые относятся к машине (например, КПП)
CREATE TABLE IF NOT EXISTS car_answers (
    car_id INTEGER NOT NULL REFERENCES cars(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    PRIMARY KEY (car_id, question)
);

-- Общая корзина
CREATE TABLE IF NOT EXISTS cart_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_json TEXT NOT NULL,            -- предложение поставщика целиком
    offer_key TEXT NOT NULL,             -- supplier:offer_id, чтобы находить одинаковые
    qty INTEGER NOT NULL CHECK (qty > 0),
    added_by_id INTEGER NOT NULL,
    added_by_name TEXT NOT NULL,
    car_id INTEGER REFERENCES cars(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Результаты поиска: кнопка «В корзину» ссылается на номер строки здесь.
-- (В кнопку Telegram влезает только 64 байта, всё предложение туда не поместить.)
CREATE TABLE IF NOT EXISTS offer_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Состояние пользователя: текущая машина и «чего бот ждёт от него» (например, VIN)
CREATE TABLE IF NOT EXISTS user_state (
    user_id INTEGER PRIMARY KEY,
    current_car_id INTEGER REFERENCES cars(id) ON DELETE SET NULL,
    pending TEXT
);

-- Незаконченные уточнения по названию детали
CREATE TABLE IF NOT EXISTS clarify_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Проверка корзины перед заказом (то, что админ видит на экране подтверждения)
CREATE TABLE IF NOT EXISTS checkout_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    cart_fingerprint TEXT NOT NULL,
    data_json TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Заказы
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier TEXT NOT NULL,
    supplier_order_id TEXT NOT NULL,
    status TEXT NOT NULL,
    total TEXT NOT NULL,
    admin_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    offer_json TEXT NOT NULL,
    qty INTEGER NOT NULL,
    car_id INTEGER REFERENCES cars(id) ON DELETE SET NULL,
    added_by_id INTEGER
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Открывает базу (создаёт файл и таблицы, если их нет)."""
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row  # строки как словари: row["plate"]
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
