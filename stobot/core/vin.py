"""VIN: проверка и определение марки.

VIN — 17 символов: латинские буквы и цифры, без I, O и Q
(их не используют, чтобы не путать с 1 и 0).

Марку определяем по первым символам (WMI — код производителя по ISO 3780).
Таблица ниже неполная: если код незнакомый,
марку просто не показываем. Модель, двигатель и год по VIN надёжно
определит только каталог — поэтому здесь мы их не угадываем.
"""

from __future__ import annotations

import re

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

# Код производителя (начало VIN) → марка. Сначала проверяются длинные коды.
_WMI = {
    # Япония
    "JTH": "Lexus",
    "JTJ": "Lexus",
    "JT": "Toyota",
    "JN": "Nissan",
    "JM": "Mazda",
    "JH": "Honda",
    "JF": "Subaru",
    "JS": "Suzuki",
    "JA": "Mitsubishi",
    "JMB": "Mitsubishi",
    # Корея
    "KMH": "Hyundai",
    "KN": "Kia",
    "KL": "Chevrolet",
    # Сборка в России
    "XTA": "Lada",
    "XW8": "Volkswagen",
    "Z94": "Hyundai",
    "X7L": "Renault",
    # Европа
    "WVW": "Volkswagen",
    "WV": "Volkswagen",
    "WBA": "BMW",
    "WDB": "Mercedes-Benz",
    "WDD": "Mercedes-Benz",
    "W1K": "Mercedes-Benz",
    "WAU": "Audi",
    "WF0": "Ford",
    "TMB": "Skoda",
    "VF1": "Renault",
    "VF3": "Peugeot",
    "VF7": "Citroen",
    "ZFA": "Fiat",
    "YV1": "Volvo",
    "WP0": "Porsche",
    "SAL": "Land Rover",
    # США и Канада (Toyota, собранные там)
    "4T": "Toyota",
    "5T": "Toyota",
    "2T": "Toyota",
}


def normalize_vin(text: str) -> str:
    """' jtnb 11hk1034 56789 ' -> 'JTNB11HK103456789'."""
    return "".join(text.upper().split()).replace("-", "")


def is_vin(text: str) -> bool:
    """Похоже ли на VIN: ровно 17 символов, есть и буквы, и цифры."""
    vin = normalize_vin(text)
    return (
        bool(_VIN_RE.match(vin)) and any(c.isdigit() for c in vin) and any(c.isalpha() for c in vin)
    )


def make_from_vin(vin: str) -> str | None:
    """Марка по коду производителя или None, если код незнакомый."""
    vin = normalize_vin(vin)
    for length in (3, 2):
        make = _WMI.get(vin[:length])
        if make:
            return make
    return None
