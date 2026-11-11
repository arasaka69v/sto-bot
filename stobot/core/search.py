"""Поиск по артикулу и выбор самого выгодного варианта."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from stobot.core.models import Offer
from stobot.suppliers.base import Supplier

log = logging.getLogger(__name__)

MAX_RESULTS = 5

# Артикул: латиница, цифры, дефисы, точки, пробелы, слэш; хотя бы одна цифра.
# Кириллица — значит, это название детали, а не артикул.
_ARTICLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-\.\s/]{2,29}$")


def looks_like_article(text: str) -> bool:
    text = text.strip()
    return bool(_ARTICLE_RE.match(text)) and any(ch.isdigit() for ch in text)


def pick_best(offers: list[Offer], normal_days: int) -> Offer | None:
    """Самый выгодный: в наличии, доставка не дольше нормы, самая низкая цена.

    При равной цене — тот, что привезут быстрее. Если ни один вариант
    не подходит под норму срока — «выгодного» нет (не подсвечиваем ничего,
    чтобы не советовать деталь, которую ждать две недели).
    """
    candidates = [o for o in offers if o.stock > 0 and o.delivery_days <= normal_days]
    if not candidates:
        return None
    return min(candidates, key=lambda o: (o.price, o.delivery_days))


def arrange(offers: list[Offer], normal_days: int, limit: int = MAX_RESULTS) -> list[Offer]:
    """Сортирует варианты для показа и оставляет не больше limit.

    Порядок: сначала то, что есть в наличии, потом по цене.
    Самый выгодный и хотя бы один оригинал всегда попадают в список,
    чтобы мастер видел их рядом.
    """
    ordered = sorted(offers, key=lambda o: (o.stock <= 0, o.price, o.delivery_days))
    shown = ordered[:limit]

    must_have = []
    best = pick_best(offers, normal_days)
    if best is not None:
        must_have.append(best)
    originals = [o for o in ordered if o.is_original]
    if originals:
        must_have.append(originals[0])

    for offer in must_have:
        if offer not in shown:
            # Заменяем последний «обычный» вариант, который не из обязательных
            for i in range(len(shown) - 1, -1, -1):
                if shown[i] not in must_have:
                    shown[i] = offer
                    break
    # После замены снова сортируем, чтобы порядок был понятным
    return sorted(shown, key=lambda o: (o.stock <= 0, o.price, o.delivery_days))


@dataclass
class SearchResult:
    article: str
    offers: list[Offer]  # уже отсортированы и обрезаны до 5
    best: Offer | None
    total_found: int
    can_show_analogs: bool
    is_analogs: bool = False


class SearchService:
    def __init__(self, supplier: Supplier, normal_days: int):
        self.supplier = supplier
        self.normal_days = normal_days

    async def by_article(self, article: str) -> SearchResult:
        article = article.strip()
        log.info("search article=%s", article)
        offers = await self.supplier.search(article)
        return self._result(article, offers, is_analogs=False)

    async def analogs(self, article: str, brand: str) -> SearchResult:
        """Аналоги вместе с оригиналом — чтобы сравнить цены рядом."""
        log.info("analogs article=%s brand=%s", article, brand)
        originals = await self.supplier.search(article)
        analogs = await self.supplier.analogs(article, brand)
        # Убираем дубли (одно и то же предложение могло прийти дважды)
        unique = {o.offer_id: o for o in [*originals, *analogs]}
        return self._result(article, list(unique.values()), is_analogs=True)

    def _result(self, article: str, offers: list[Offer], is_analogs: bool) -> SearchResult:
        return SearchResult(
            article=article,
            offers=arrange(offers, self.normal_days),
            best=pick_best(offers, self.normal_days),
            total_found=len(offers),
            can_show_analogs=self.supplier.supports_analogs and not is_analogs and bool(offers),
            is_analogs=is_analogs,
        )
