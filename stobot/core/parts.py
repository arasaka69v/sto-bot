"""Справочник типов деталей и уточняющих вопросов.

Здесь НЕТ артикулов — только «что это за деталь» и «что нужно уточнить».
Артикул бот берёт только из каталога или от мастера.

Чтобы добавить деталь: допишите PartType в PARTS. Чтобы добавить
уточнение: допишите Question в QUESTIONS и укажите его в нужной детали.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    key: str
    title: str  # как вопрос показывается мастеру
    options: tuple[tuple[str, str], ...]  # (значение, подпись на кнопке); пусто — ввод текстом
    # "car" — ответ относится к машине, запоминаем (двигатель, КПП);
    # "request" — относится к конкретному ремонту (сторона, ось), не запоминаем:
    # сегодня меняли передние колодки, а через месяц понадобятся задние.
    scope: str = "request"
    # Слова-подсказки в тексте мастера: «колодки перед» → ось = перед
    hints: tuple[tuple[str, str], ...] = ()

    @property
    def free_text(self) -> bool:
        return not self.options

    def label(self, value: str) -> str:
        for v, text in self.options:
            if v == value:
                return text
        return value


QUESTIONS: dict[str, Question] = {
    q.key: q
    for q in (
        Question(
            "axle",
            "Ось",
            (("front", "Передние"), ("rear", "Задние")),
            hints=(("перед", "front"), ("перёд", "front"), ("зад", "rear")),
        ),
        Question(
            "side",
            "Сторона",
            (("left", "Левый"), ("right", "Правый")),
            hints=(("лев", "left"), ("прав", "right")),
        ),
        Question(
            "cv_position",
            "ШРУС",
            (("outer", "Наружный"), ("inner", "Внутренний")),
            hints=(("наруж", "outer"), ("внешн", "outer"), ("внутр", "inner")),
        ),
        Question(
            "mount_position",
            "Какая опора",
            (("front", "Передняя"), ("rear", "Задняя"), ("left", "Левая"), ("right", "Правая")),
            hints=(("перед", "front"), ("зад", "rear"), ("лев", "left"), ("прав", "right")),
        ),
        Question(
            "transmission",
            "КПП",
            (("at", "АКПП"), ("mt", "МКПП"), ("cvt", "Вариатор")),
            scope="car",
            hints=(
                ("акпп", "at"),
                ("автомат", "at"),
                ("мкпп", "mt"),
                ("механик", "mt"),
                ("вариатор", "cvt"),
                ("cvt", "cvt"),
            ),
        ),
        Question("engine", "Двигатель", (), scope="car"),
    )
}


@dataclass(frozen=True)
class PartType:
    key: str
    title: str
    synonyms: tuple[str, ...]  # как детали называют мастера (в т.ч. по-народному)
    questions: tuple[str, ...] = ()  # ключи из QUESTIONS — только то, без чего не подобрать


PARTS: dict[str, PartType] = {
    p.key: p
    for p in (
        PartType(
            "cv_joint",
            "ШРУС",
            ("шрус", "граната", "гранату", "шарнир равных угловых"),
            ("side", "cv_position"),
        ),
        PartType("brake_pads", "Тормозные колодки", ("колодки", "тормозные колодки"), ("axle",)),
        PartType(
            "brake_discs", "Тормозные диски", ("тормозной диск", "тормозные диски"), ("axle",)
        ),
        PartType(
            "engine_mount",
            "Опора двигателя",
            ("опора двигателя", "подушка двигателя", "подушка двигла", "подушка", "подушка мотора"),
            ("mount_position", "transmission"),
        ),
        PartType(
            "shock_absorber", "Амортизатор", ("амортизатор", "аморт", "стойка"), ("axle", "side")
        ),
        PartType(
            "stabilizer_link",
            "Стойка стабилизатора",
            ("стойка стабилизатора", "косточка", "линк стабилизатора"),
            ("axle", "side"),
        ),
        PartType("ball_joint", "Шаровая опора", ("шаровая", "шаровая опора", "шаровую"), ("side",)),
        PartType(
            "tie_rod_end",
            "Рулевой наконечник",
            ("рулевой наконечник", "наконечник рулевой", "наконечник"),
            ("side",),
        ),
        PartType(
            "wheel_bearing",
            "Ступичный подшипник",
            ("ступичный подшипник", "подшипник ступицы", "ступица"),
            ("axle", "side"),
        ),
        PartType("oil_filter", "Масляный фильтр", ("масляный фильтр", "фильтр масла"), ("engine",)),
        PartType(
            "air_filter", "Воздушный фильтр", ("воздушный фильтр", "фильтр воздуха"), ("engine",)
        ),
        # Где уточнять нечего — вопросов нет
        PartType("cabin_filter", "Салонный фильтр", ("салонный фильтр", "фильтр салона")),
        PartType(
            "spark_plugs", "Свечи зажигания", ("свечи", "свечи зажигания", "свеча"), ("engine",)
        ),
        PartType("timing_belt", "Ремень ГРМ", ("ремень грм", "грм"), ("engine",)),
        PartType("battery", "Аккумулятор", ("аккумулятор", "акб", "аккум")),
        PartType("wiper_blades", "Щётки стеклоочистителя", ("дворники", "щетки", "щётки")),
    )
}
