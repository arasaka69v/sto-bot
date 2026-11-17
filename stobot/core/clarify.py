"""Логика уточняющих вопросов при поиске по названию детали.

Правила:
1. Спрашиваем только то, что есть в списке вопросов детали (без чего не подобрать).
2. Не спрашиваем то, что уже известно: из текста мастера, из машины
   (двигатель), из прошлых ответов по этой машине (КПП) или из VIN
   (если подключён каталог — он сам знает двигатель и КПП по VIN).
3. Если у вопроса всего один вариант ответа — не спрашиваем, берём его.
4. Все вопросы — одним сообщением с кнопками (это делает app.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stobot.core.models import Car
from stobot.core.parts import PARTS, QUESTIONS, PartType, Question


def known_answers(
    part: PartType, text_answers: dict[str, str], car: Car | None, car_answers: dict[str, str]
) -> dict[str, str]:
    """Собирает всё, что уже известно, из трёх источников."""
    known: dict[str, str] = {}
    for key in part.questions:
        question = QUESTIONS[key]
        if question.scope == "car":
            if key == "engine" and car and car.engine:
                known[key] = car.engine
            elif key in car_answers:
                known[key] = car_answers[key]
    # То, что мастер написал прямо сейчас, важнее сохранённого
    known.update({k: v for k, v in text_answers.items() if k in part.questions})
    return known


def questions_to_ask(
    part: PartType, known: dict[str, str], vin_known: bool = False
) -> list[Question]:
    """Какие вопросы задать. vin_known=True — у машины есть VIN, и каталог сам
    знает двигатель и КПП, поэтому вопросы «про машину» не задаём."""
    result = []
    for key in part.questions:
        question = QUESTIONS[key]
        if key in known:
            continue
        if vin_known and question.scope == "car":
            continue
        if len(question.options) == 1:
            continue  # единственный вариант — спрашивать нечего
        result.append(question)
    return result


def auto_answers(part: PartType) -> dict[str, str]:
    """Ответы на вопросы с единственным вариантом."""
    return {
        key: QUESTIONS[key].options[0][0]
        for key in part.questions
        if len(QUESTIONS[key].options) == 1
    }


@dataclass
class ClarifyState:
    """Состояние уточнения. Хранится в базе как JSON между нажатиями кнопок."""

    part_key: str
    car_id: int | None
    answers: dict[str, str] = field(default_factory=dict)
    ask: list[str] = field(default_factory=list)  # какие вопросы задали

    @property
    def part(self) -> PartType:
        return PARTS[self.part_key]

    @property
    def missing(self) -> list[str]:
        return [k for k in self.ask if k not in self.answers]

    @property
    def done(self) -> bool:
        return not self.missing

    def to_dict(self) -> dict:
        return {
            "part_key": self.part_key,
            "car_id": self.car_id,
            "answers": self.answers,
            "ask": self.ask,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ClarifyState:
        return cls(**data)

    def summary(self) -> str:
        """«Тормозные колодки, Передние» — для показа мастеру."""
        parts = [self.part.title]
        for key in self.part.questions:
            if key in self.answers:
                parts.append(QUESTIONS[key].label(self.answers[key]))
        return ", ".join(parts)


def start(
    part_key: str,
    text_answers: dict[str, str],
    car: Car | None,
    car_answers: dict[str, str],
    vin_known: bool = False,
) -> ClarifyState:
    """Начало уточнения: определяем, что ещё нужно спросить."""
    part = PARTS[part_key]
    known = auto_answers(part) | known_answers(part, text_answers, car, car_answers)
    ask = [q.key for q in questions_to_ask(part, known, vin_known)]
    return ClarifyState(part_key=part_key, car_id=car.id if car else None, answers=known, ask=ask)


def apply_answer(state: ClarifyState, question_key: str, value: str) -> ClarifyState:
    """Записывает ответ. Неизвестный вопрос или вариант — игнорируем."""
    if question_key not in state.ask:
        return state
    question = QUESTIONS[question_key]
    if question.options and value not in {v for v, _ in question.options}:
        return state
    value = value.strip()
    if not value:
        return state
    state.answers[question_key] = value
    return state
