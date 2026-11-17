"""Выбор распознавателя: с ключом ИИ — словарь + ИИ, без ключа — только словарь."""

from __future__ import annotations

from stobot.ai.base import PartRecognizer


def create_recognizer(api_key: str, model: str) -> PartRecognizer:
    if api_key:
        from stobot.ai.llm import AIRecognizer

        return AIRecognizer(api_key, model)
    from stobot.ai.dictionary import DictionaryRecognizer

    return DictionaryRecognizer()
