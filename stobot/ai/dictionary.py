"""Распознавание по встроенному словарю — работает без ИИ и без интернета.

Опечатки ловим «нечётким» сравнением: «калодки» похоже на «колодки» на 86%,
этого достаточно. Сравнение делает стандартный модуль difflib.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from stobot.ai.base import PartRecognizer, Recognition
from stobot.core.parts import PARTS, QUESTIONS

# Насколько слово должно быть похоже на слово из словаря (0..1)
SIMILARITY = 0.8


def _words(text: str) -> list[str]:
    text = text.lower().replace("ё", "е")
    return re.findall(r"[a-zа-я0-9]+", text)


def _word_score(word: str, tokens: list[str]) -> float:
    """Насколько хорошо слово из словаря нашлось среди слов мастера."""
    best = 0.0
    for token in tokens:
        if token == word:
            return 1.0
        # Короткие слова (акб, грм) — только точное совпадение, иначе много ложных
        if len(word) < 4 or len(token) < 4:
            continue
        # «колодок», «колодками» — то же слово с другим окончанием
        if token.startswith(word[:-1]) or word.startswith(token[:-1]):
            best = max(best, 0.95)
        best = max(best, SequenceMatcher(None, word, token).ratio())
    return best


def extract_answers(text: str, question_keys: tuple[str, ...]) -> dict[str, str]:
    """Достаёт из текста ответы на вопросы: «колодки перед» → {"axle": "front"}."""
    tokens = _words(text)
    answers: dict[str, str] = {}
    for key in question_keys:
        question = QUESTIONS[key]
        for stem, value in question.hints:
            if any(token.startswith(stem) for token in tokens):
                answers[key] = value
                break
    return answers


class DictionaryRecognizer(PartRecognizer):
    async def recognize(self, text: str) -> Recognition:
        return self.recognize_sync(text)

    def recognize_sync(self, text: str) -> Recognition:
        tokens = _words(text)
        best_key, best_score, best_len = None, 0.0, 0
        for part in PARTS.values():
            for synonym in part.synonyms:
                words = _words(synonym)
                scores = [_word_score(w, tokens) for w in words]
                if min(scores) < SIMILARITY:
                    continue  # хотя бы одно слово не нашлось
                score = sum(scores) / len(scores)
                # Лучше более точное совпадение; при равенстве — более длинный синоним
                # («стойка стабилизатора» точнее, чем просто «стойка»)
                if (score, len(words)) > (best_score, best_len):
                    best_key, best_score, best_len = part.key, score, len(words)
        if best_key is None:
            return Recognition(part_key=None, source="dictionary")
        answers = extract_answers(text, PARTS[best_key].questions)
        return Recognition(part_key=best_key, answers=answers, source="dictionary")
