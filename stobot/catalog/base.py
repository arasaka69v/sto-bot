"""Интерфейс каталога по VIN: тип детали + уточнения + машина → артикулы.

Сейчас реального каталога нет — используется заглушка (stub.py).
Когда появится каталог, напишите класс с этими методами и подключите
его в stobot/catalog/__init__.py. Остальной код менять не нужно.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from stobot.core.models import Car


class VinCatalog(ABC):
    @abstractmethod
    def is_available(self) -> bool:
        """Может ли каталог подбирать артикулы."""

    @abstractmethod
    async def find_articles(
        self, part_key: str, answers: dict[str, str], car: Car | None
    ) -> list[str]:
        """Артикулы из каталога. Пустой список — подобрать не удалось."""
