"""Заглушка каталога: честно говорит, что подбирать по названию не умеет.

Артикулы НИКОГДА не придумываем — поэтому всегда пустой список.
"""

from __future__ import annotations

from stobot.catalog.base import VinCatalog
from stobot.core.models import Car


class StubCatalog(VinCatalog):
    def is_available(self) -> bool:
        return False

    async def find_articles(
        self, part_key: str, answers: dict[str, str], car: Car | None
    ) -> list[str]:
        return []
