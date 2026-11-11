"""Тесты поиска и выбора самого выгодного."""

from stobot.core.search import arrange, looks_like_article, pick_best
from stobot.suppliers.mock import MockSupplier
from tests.conftest import run


def all_pads():
    s = MockSupplier()
    return run(s.search("04465-33471")) + run(s.analogs("04465-33471", "TOYOTA"))


def test_article_detection():
    assert looks_like_article("04465-33471")
    assert looks_like_article("90915-YZZE1")
    assert looks_like_article("W 68/3")
    assert not looks_like_article("колодки перед")
    assert not looks_like_article("масло 5w30")
    assert not looks_like_article("ABCDEF")  # нет цифр


def test_best_is_cheapest_in_stock_with_normal_delivery():
    best = pick_best(all_pads(), normal_days=3)
    # ROSSKO-TEST 9 900 (3 дня) дешевле KASHIYAMA 12 900, у которой 6 дней
    assert best.brand == "ROSSKO-TEST"
    best = pick_best(all_pads(), normal_days=2)
    assert best.brand == "NIBK"


def test_no_best_when_nothing_fits():
    pads = [o for o in all_pads() if o.delivery_days > 5]
    assert pick_best(pads, normal_days=3) is None


def test_arrange_keeps_original_and_best_in_top5():
    shown = arrange(all_pads(), normal_days=3)
    assert len(shown) == 5
    assert any(o.is_original for o in shown)
    assert pick_best(all_pads(), 3) in shown
    # Без наличия — в конце
    stock = [o.stock > 0 for o in shown]
    assert stock == sorted(stock, reverse=True)


def test_promo_only_from_supplier():
    pads = all_pads()
    promos = {o.brand: o.promo for o in pads if o.promo}
    assert promos == {"TRW": "Акция: -10%"}
