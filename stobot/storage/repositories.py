"""Работа с таблицами. Весь SQL — здесь, логика бота SQL не видит.

Каждый класс отвечает за одну тему: машины, корзина, заказы и т.д.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

from stobot.core.models import Car, CartItem, Offer, Order, OrderLine, PlacedOrder


def normalize_plate(plate: str) -> str:
    """'123 abc 01' -> '123ABC01'. Кириллицу, похожую на латиницу, тоже приводим."""
    lookalikes = str.maketrans("АВЕКМНОРСТУХ", "ABEKMHOPCTYX")
    return "".join(plate.upper().split()).replace("-", "").translate(lookalikes)


def _row_to_car(row: sqlite3.Row | None) -> Car | None:
    if row is None:
        return None
    return Car(
        id=row["id"],
        plate=row["plate"],
        model=row["model"],
        vin=row["vin"],
        engine=row["engine"],
        year=row["year"],
    )


class CarRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, car_id: int) -> Car | None:
        row = self.conn.execute("SELECT * FROM cars WHERE id = ?", (car_id,)).fetchone()
        return _row_to_car(row)

    def find_by_plate(self, plate: str) -> Car | None:
        row = self.conn.execute(
            "SELECT * FROM cars WHERE plate = ?", (normalize_plate(plate),)
        ).fetchone()
        return _row_to_car(row)

    def create_or_update(self, plate: str, model: str) -> Car:
        plate = normalize_plate(plate)
        existing = self.find_by_plate(plate)
        if existing:
            if model and model != existing.model:
                self.conn.execute("UPDATE cars SET model = ? WHERE id = ?", (model, existing.id))
                self.conn.commit()
            return self.get(existing.id)  # type: ignore[return-value]
        cur = self.conn.execute("INSERT INTO cars (plate, model) VALUES (?, ?)", (plate, model))
        self.conn.commit()
        return self.get(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def update_field(self, car_id: int, field: str, value: str | int | None) -> None:
        if field not in ("vin", "engine", "year", "model"):
            raise ValueError(f"Нельзя менять поле {field}")
        self.conn.execute(f"UPDATE cars SET {field} = ? WHERE id = ?", (value, car_id))
        self.conn.commit()

    def recent(self, limit: int = 6) -> list[Car]:
        rows = self.conn.execute("SELECT * FROM cars ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_car(r) for r in rows]  # type: ignore[misc]

    def answers(self, car_id: int) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT question, answer FROM car_answers WHERE car_id = ?", (car_id,)
        ).fetchall()
        return {r["question"]: r["answer"] for r in rows}

    def save_answer(self, car_id: int, question: str, answer: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO car_answers (car_id, question, answer) VALUES (?, ?, ?)",
            (car_id, question, answer),
        )
        self.conn.commit()


class CartRepo:
    def __init__(self, conn: sqlite3.Connection, cars: CarRepo):
        self.conn = conn
        self.cars = cars

    def _to_item(self, row: sqlite3.Row) -> CartItem:
        car = self.cars.get(row["car_id"]) if row["car_id"] else None
        return CartItem(
            id=row["id"],
            offer=Offer.from_dict(json.loads(row["offer_json"])),
            qty=row["qty"],
            added_by_id=row["added_by_id"],
            added_by_name=row["added_by_name"],
            car=car,
        )

    def all(self) -> list[CartItem]:
        rows = self.conn.execute("SELECT * FROM cart_items ORDER BY id").fetchall()
        return [self._to_item(r) for r in rows]

    def get(self, item_id: int) -> CartItem | None:
        row = self.conn.execute("SELECT * FROM cart_items WHERE id = ?", (item_id,)).fetchone()
        return self._to_item(row) if row else None

    def find_same(self, offer: Offer, car_id: int | None) -> CartItem | None:
        row = self.conn.execute(
            "SELECT * FROM cart_items WHERE offer_key = ? AND car_id IS ?",
            (f"{offer.supplier}:{offer.offer_id}", car_id),
        ).fetchone()
        return self._to_item(row) if row else None

    def add(self, offer: Offer, qty: int, user_id: int, user_name: str, car_id: int | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO cart_items"
            " (offer_json, offer_key, qty, added_by_id, added_by_name, car_id)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                json.dumps(offer.to_dict(), ensure_ascii=False),
                f"{offer.supplier}:{offer.offer_id}",
                qty,
                user_id,
                user_name,
                car_id,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def set_qty(self, item_id: int, qty: int) -> None:
        self.conn.execute("UPDATE cart_items SET qty = ? WHERE id = ?", (qty, item_id))
        self.conn.commit()

    def remove(self, item_id: int) -> None:
        self.conn.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
        self.conn.commit()

    def remove_many(self, item_ids: list[int]) -> None:
        self.conn.executemany("DELETE FROM cart_items WHERE id = ?", [(i,) for i in item_ids])
        self.conn.commit()


class SnapshotRepo:
    """Хранит предложения из результатов поиска для кнопок «В корзину»."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, offer: Offer) -> int:
        cur = self.conn.execute(
            "INSERT INTO offer_snapshots (offer_json) VALUES (?)",
            (json.dumps(offer.to_dict(), ensure_ascii=False),),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get(self, snapshot_id: int) -> Offer | None:
        row = self.conn.execute(
            "SELECT offer_json FROM offer_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        return Offer.from_dict(json.loads(row["offer_json"])) if row else None

    def cleanup(self, days: int = 7) -> None:
        """Старые результаты поиска не нужны — удаляем, чтобы база не росла."""
        self.conn.execute(
            "DELETE FROM offer_snapshots WHERE created_at < datetime('now', ?)", (f"-{days} days",)
        )
        self.conn.commit()


class UserStateRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _ensure(self, user_id: int) -> None:
        self.conn.execute("INSERT OR IGNORE INTO user_state (user_id) VALUES (?)", (user_id,))

    def current_car_id(self, user_id: int) -> int | None:
        row = self.conn.execute(
            "SELECT current_car_id FROM user_state WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["current_car_id"] if row else None

    def set_current_car(self, user_id: int, car_id: int | None) -> None:
        self._ensure(user_id)
        self.conn.execute(
            "UPDATE user_state SET current_car_id = ? WHERE user_id = ?", (car_id, user_id)
        )
        self.conn.commit()

    def pending(self, user_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT pending FROM user_state WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["pending"] if row else None

    def set_pending(self, user_id: int, pending: str | None) -> None:
        self._ensure(user_id)
        self.conn.execute("UPDATE user_state SET pending = ? WHERE user_id = ?", (pending, user_id))
        self.conn.commit()


class JsonSessionRepo:
    """Небольшие «сессии» (уточнения, проверка заказа) в виде JSON."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_clarify(self, user_id: int, data: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO clarify_sessions (user_id, data_json) VALUES (?, ?)",
            (user_id, json.dumps(data, ensure_ascii=False)),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_clarify(self, session_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT data_json FROM clarify_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return json.loads(row["data_json"]) if row else None

    def update_clarify(self, session_id: int, data: dict) -> None:
        self.conn.execute(
            "UPDATE clarify_sessions SET data_json = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), session_id),
        )
        self.conn.commit()

    def create_checkout(self, admin_id: int, fingerprint: str, data: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO checkout_sessions (admin_id, cart_fingerprint, data_json)"
            " VALUES (?, ?, ?)",
            (admin_id, fingerprint, json.dumps(data, ensure_ascii=False)),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_checkout(self, session_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT *, (created_at < datetime('now', '-15 minutes')) AS expired"
            " FROM checkout_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()

    def mark_checkout_used(self, session_id: int) -> bool:
        """Помечает проверку использованной. False — уже была использована
        (защита от двойного нажатия «Подтвердить»)."""
        cur = self.conn.execute(
            "UPDATE checkout_sessions SET used = 1 WHERE id = ? AND used = 0", (session_id,)
        )
        self.conn.commit()
        return cur.rowcount == 1

    def unmark_checkout(self, session_id: int) -> None:
        self.conn.execute("UPDATE checkout_sessions SET used = 0 WHERE id = ?", (session_id,))
        self.conn.commit()


class OrderRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(
        self,
        supplier: str,
        placed: PlacedOrder,
        lines: list[OrderLine],
        total: Decimal,
        admin_id: int,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO orders (supplier, supplier_order_id, status, total, admin_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (supplier, placed.supplier_order_id, placed.status, str(total), admin_id),
        )
        order_id = cur.lastrowid
        self.conn.executemany(
            "INSERT INTO order_lines (order_id, offer_json, qty, car_id, added_by_id)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (
                    order_id,
                    json.dumps(line.offer.to_dict(), ensure_ascii=False),
                    line.qty,
                    line.car_id,
                    line.added_by_id,
                )
                for line in lines
            ],
        )
        self.conn.commit()
        return order_id  # type: ignore[return-value]

    def _lines(self, order_id: int, car_id: int | None = None) -> list[dict]:
        sql = (
            "SELECT ol.*, c.plate, c.model FROM order_lines ol"
            " LEFT JOIN cars c ON c.id = ol.car_id WHERE ol.order_id = ?"
        )
        params: list = [order_id]
        if car_id is not None:
            sql += " AND ol.car_id = ?"
            params.append(car_id)
        result = []
        for row in self.conn.execute(sql, params).fetchall():
            result.append(
                {
                    "offer": Offer.from_dict(json.loads(row["offer_json"])),
                    "qty": row["qty"],
                    "car": f"{row['model']} {row['plate']}".strip() if row["plate"] else None,
                }
            )
        return result

    def _to_order(self, row: sqlite3.Row, car_id: int | None = None) -> Order:
        return Order(
            id=row["id"],
            supplier=row["supplier"],
            supplier_order_id=row["supplier_order_id"],
            status=row["status"],
            total=Decimal(row["total"]),
            created_at=row["created_at"],
            lines=self._lines(row["id"], car_id),
        )

    def recent(self, limit: int = 10) -> list[Order]:
        rows = self.conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._to_order(r) for r in rows]

    def for_car(self, car_id: int, limit: int = 20) -> list[Order]:
        rows = self.conn.execute(
            "SELECT DISTINCT o.* FROM orders o JOIN order_lines ol ON ol.order_id = o.id"
            " WHERE ol.car_id = ? ORDER BY o.id DESC LIMIT ?",
            (car_id, limit),
        ).fetchall()
        return [self._to_order(r, car_id) for r in rows]

    def update_status(self, order_id: int, status: str) -> None:
        self.conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        self.conn.commit()
