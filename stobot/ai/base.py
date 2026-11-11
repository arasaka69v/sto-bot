"""Интерфейс распознавания: текст мастера → тип детали + то, что уже понятно из текста."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Recognition:
    part_key: str | None  # ключ из stobot/core/parts.py или None — не поняли
    answers: dict[str, str] = field(default_factory=dict)  # например {"axle": "front"}
    source: str = ""  # "dictionary" или "ai" — для логов


class PartRecognizer(ABC):
    @abstractmethod
    async def recognize(self, text: str) -> Recognition:
        """Никогда не возвращает артикул — только тип детали."""
