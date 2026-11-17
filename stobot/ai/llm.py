"""Распознавание названий деталей через ИИ (Anthropic API).

Включается, только если в .env указан ANTHROPIC_API_KEY.
Сначала бот пробует словарь (быстро и бесплатно), и только если словарь
не понял — спрашивает ИИ.

ИИ может выбрать ТОЛЬКО тип детали из нашего справочника. Ответ ограничен
JSON-схемой (structured outputs), поэтому вернуть артикул ИИ не может.
"""

from __future__ import annotations

import json
import logging

import anthropic

from stobot.ai.base import PartRecognizer, Recognition
from stobot.ai.dictionary import DictionaryRecognizer, extract_answers
from stobot.core.parts import PARTS, QUESTIONS

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Ты помогаешь мастерам автосервиса в Казахстане. Мастер пишет название "
    "запчасти по-народному, сокращённо или с ошибками. Определи, какой тип детали "
    "из списка он имеет в виду, и какие уточнения уже есть в его тексте. "
    "Если не уверен — выбери unknown. Не додумывай уточнения, которых нет в тексте."
)


def _schema() -> dict:
    answer_props = {
        key: {"type": "string", "enum": [v for v, _ in q.options] + ["unknown"]}
        for key, q in QUESTIONS.items()
        if q.options
    }
    return {
        "type": "object",
        "properties": {
            "part_key": {"type": "string", "enum": [*PARTS.keys(), "unknown"]},
            "answers": {
                "type": "object",
                "properties": answer_props,
                "required": list(answer_props),
                "additionalProperties": False,
            },
        },
        "required": ["part_key", "answers"],
        "additionalProperties": False,
    }


def _catalog_text() -> str:
    lines = [f"- {p.key}: {p.title} (говорят: {', '.join(p.synonyms)})" for p in PARTS.values()]
    return "Типы деталей:\n" + "\n".join(lines)


class AIRecognizer(PartRecognizer):
    def __init__(self, api_key: str, model: str):
        # Таймаут 20 с и 1 повтор: мастер не должен ждать минуту
        self.client = anthropic.AsyncAnthropic(api_key=api_key, timeout=20.0, max_retries=1)
        self.model = model
        self.dictionary = DictionaryRecognizer()

    async def recognize(self, text: str) -> Recognition:
        quick = self.dictionary.recognize_sync(text)
        if quick.part_key:
            return quick
        try:
            return await self._ask_ai(text)
        except Exception:
            # ИИ недоступен — не страшно, мастер просто пришлёт артикул
            log.exception("AI recognition failed")
            return Recognition(part_key=None, source="ai-error")

    async def _ask_ai(self, text: str) -> Recognition:
        log.info("AI recognize request, text_len=%d", len(text))
        response = await self.client.beta.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            # Если модель откажется отвечать, сервер сам повторит запрос другой моделью
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": "low",  # простая классификация — глубоко думать не нужно
                "format": {"type": "json_schema", "schema": _schema()},
            },
            messages=[{"role": "user", "content": f"{_catalog_text()}\n\nМастер написал: {text}"}],
        )
        if response.stop_reason == "refusal":
            log.warning("AI refused to classify")
            return Recognition(part_key=None, source="ai")
        raw = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(raw)
        part_key = data.get("part_key")
        if part_key not in PARTS:
            return Recognition(part_key=None, source="ai")

        allowed = PARTS[part_key].questions
        answers = {
            k: v for k, v in data.get("answers", {}).items() if k in allowed and v != "unknown"
        }
        # Подсказки из текста по словарю надёжнее — они важнее ответа ИИ
        answers |= extract_answers(text, allowed)
        log.info("AI recognized part=%s answers=%s", part_key, answers)
        return Recognition(part_key=part_key, answers=answers, source="ai")
