"""Выбор поставщика по настройке SUPPLIER из .env."""

from __future__ import annotations

from stobot.suppliers.base import Supplier


def create_supplier(name: str) -> Supplier:
    if name == "mock":
        from stobot.suppliers.mock import MockSupplier

        return MockSupplier()
    if name == "rossko":
        from stobot.suppliers.rossko import create_rossko_supplier

        return create_rossko_supplier()
    raise ValueError(f"Неизвестный поставщик: {name}")
