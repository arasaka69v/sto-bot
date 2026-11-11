"""Выбор каталога по VIN. Пока есть только заглушка."""

from __future__ import annotations

from stobot.catalog.base import VinCatalog


def create_catalog() -> VinCatalog:
    from stobot.catalog.stub import StubCatalog

    return StubCatalog()
