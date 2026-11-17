"""Клиент Росско на подставных ответах в точном формате из docs/rossko/*.wsdl."""

import xml.etree.ElementTree as ET
from decimal import Decimal

import httpx
import pytest

from stobot.config import RosskoConfig
from stobot.core.models import OrderLine
from stobot.suppliers import rossko_soap as soap
from stobot.suppliers.base import OrderRejected, SupplierUnavailable
from stobot.suppliers.rossko import RosskoNotReady, RosskoSupplier
from stobot.suppliers.rossko_soap import RosskoAuthError
from tests.conftest import run

CONFIG = RosskoConfig(
    key1="k1",
    key2="k2",
    delivery_id="000000001",
    address_id=55,
    payment_id=1,
    contact_name="Ерлан",
    contact_phone="+77010000000",
)


def envelope(method: str, result: str, inner: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"'
        ' xmlns:ns1="https://api.rossko.ru/"><SOAP-ENV:Body>'
        f"<ns1:{method}Response><ns1:{result}>{inner}</ns1:{result}></ns1:{method}Response>"
        "</SOAP-ENV:Body></SOAP-ENV:Envelope>"
    )


def stock(sid, price, count, delivery, mult=1, desc=""):
    d = f"<ns1:description>{desc}</ns1:description>" if desc else ""
    return (
        f"<ns1:stock><ns1:id>{sid}</ns1:id><ns1:price>{price}</ns1:price>"
        f"<ns1:count>{count}</ns1:count><ns1:multiplicity>{mult}</ns1:multiplicity>"
        f"<ns1:type>1</ns1:type><ns1:delivery>{delivery}</ns1:delivery>{d}</ns1:stock>"
    )


SEARCH_OK = envelope(
    "GetSearch",
    "SearchResult",
    "<ns1:success>true</ns1:success><ns1:PartsList><ns1:Part>"
    "<ns1:guid>G1</ns1:guid><ns1:brand>TOYOTA</ns1:brand>"
    "<ns1:partnumber>04465-33471</ns1:partnumber><ns1:name>Колодки</ns1:name>"
    f"<ns1:stocks>{stock('S1', '38500.00', 4, 2)}</ns1:stocks>"
    "<ns1:crosses><ns1:Part><ns1:guid>G2</ns1:guid><ns1:brand>TRW</ns1:brand>"
    "<ns1:partnumber>GDB3425</ns1:partnumber><ns1:name>Колодки TRW</ns1:name>"
    f"<ns1:stocks>{stock('S7', '21 900,50', 10, 1, mult=2, desc='Под заказ')}</ns1:stocks>"
    "</ns1:Part></ns1:crosses></ns1:Part></ns1:PartsList>",
)


class FakeRossko:
    """Подставной сервер: отвечает заготовками и запоминает запросы."""

    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.requests: list[tuple[str, ET.Element]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        self.requests.append((method, ET.fromstring(request.content)))
        return httpx.Response(200, text=self.responses[method])


@pytest.fixture
def fake(monkeypatch):
    server = FakeRossko({"GetSearch": SEARCH_OK})
    monkeypatch.setattr(soap, "TRANSPORT", httpx.MockTransport(server.handler))
    return server


def sent_fields(element: ET.Element) -> dict:
    """Вложенные поля запроса в виде словаря (без пространств имён)."""
    result = {}
    for c in element:
        name = c.tag.rsplit("}", 1)[-1]
        result.setdefault(name, []).append(sent_fields(c) if len(c) else c.text)
    return result


def body_of(request_root: ET.Element) -> dict:
    body = request_root[0][0]
    return sent_fields(body)


def test_needs_settings():
    with pytest.raises(RosskoNotReady, match="ROSSKO_KEY1"):
        RosskoSupplier(RosskoConfig())


def test_search_parses_parts_stocks_and_crosses(fake):
    supplier = RosskoSupplier(CONFIG)
    offers = run(supplier.search("04465-33471"))
    assert len(offers) == 1
    toyota = offers[0]
    assert (toyota.brand, toyota.article, toyota.price, toyota.stock, toyota.delivery_days) == (
        "TOYOTA",
        "04465-33471",
        Decimal("38500.00"),
        4,
        2,
    )
    assert toyota.is_original is False and toyota.promo is None  # в API таких признаков нет

    analogs = run(supplier.analogs("04465-33471", "TOYOTA"))
    trw = analogs[0]
    assert trw.price == Decimal("21900.50") and trw.multiplicity == 2 and trw.note == "Под заказ"
    assert len(fake.requests) == 1  # аналоги взяты из того же ответа (кэш)

    fields = body_of(fake.requests[0][1])
    assert fields == {
        "KEY1": ["k1"],
        "KEY2": ["k2"],
        "text": ["04465-33471"],
        "delivery_id": ["000000001"],
        "address_id": ["55"],
    }
    assert fake.requests[0][1][0][0].tag == "{https://api.rossko.ru/}GetSearch"


def test_not_found_returns_empty(fake):
    fake.responses["GetSearch"] = envelope(
        "GetSearch",
        "SearchResult",
        "<ns1:success>false</ns1:success><ns1:message>Ничего не найдено</ns1:message>",
    )
    assert run(RosskoSupplier(CONFIG).search("XXX")) == []


def test_bad_keys(fake):
    fake.responses["GetSearch"] = envelope(
        "GetSearch",
        "SearchResult",
        "<ns1:success>false</ns1:success><ns1:message>Неверный KEY1 и/или KEY2</ns1:message>",
    )
    with pytest.raises(RosskoAuthError):
        run(RosskoSupplier(CONFIG).search("04465-33471"))


def test_network_error_is_unavailable(monkeypatch):
    def broken(request):
        raise httpx.ConnectError("нет сети")

    monkeypatch.setattr(soap, "TRANSPORT", httpx.MockTransport(broken))
    with pytest.raises(SupplierUnavailable):
        run(RosskoSupplier(CONFIG).search("04465-33471"))


def test_refresh_finds_same_stock_without_cache(fake):
    supplier = RosskoSupplier(CONFIG)
    trw = run(supplier.analogs("04465-33471", ""))[0]
    fresh = run(supplier.refresh_offer(trw))
    assert fresh.offer_id == trw.offer_id
    assert len(fake.requests) == 2  # перепроверка всегда идёт в API заново


def test_checkout_request_and_partial_reject(fake):
    supplier = RosskoSupplier(CONFIG)
    offers = run(supplier.search("04465-33471")) + run(supplier.analogs("04465-33471", ""))
    fake.responses["GetCheckout"] = envelope(
        "GetCheckout",
        "CheckoutResult",
        "<ns1:success>true</ns1:success><ns1:OrderIDS><ns1:id>7001</ns1:id></ns1:OrderIDS>"
        "<ns1:ItemsErrorList><ns1:ItemError><ns1:partnumber>GDB3425</ns1:partnumber>"
        "<ns1:brand>TRW</ns1:brand><ns1:count>2</ns1:count><ns1:stock>S7</ns1:stock>"
        "<ns1:message>Недостаточно на складе</ns1:message></ns1:ItemError></ns1:ItemsErrorList>",
    )
    placed = run(
        supplier.place_order([OrderLine(offers[0], 2), OrderLine(offers[1], 2)], "из бота")
    )
    assert placed.supplier_order_id == "7001"
    assert placed.rejected == (("TRW", "GDB3425", "Недостаточно на складе"),)

    fields = body_of(fake.requests[-1][1])
    assert fields["delivery"] == [{"delivery_id": ["000000001"], "address_id": ["55"]}]
    assert fields["payment"] == [{"payment_id": ["1"]}]
    assert fields["contact"] == [
        {"name": ["Ерлан"], "phone": ["+77010000000"], "comment": ["из бота"]}
    ]
    assert fields["delivery_parts"] == ["false"]
    parts = fields["PARTS"][0]["Part"]
    assert parts[0] == {
        "partnumber": ["04465-33471"],
        "brand": ["TOYOTA"],
        "stock": ["S1"],
        "count": ["2"],
    }


def test_checkout_rejected(fake):
    supplier = RosskoSupplier(CONFIG)
    offer = run(supplier.search("04465-33471"))[0]
    fake.responses["GetCheckout"] = envelope(
        "GetCheckout",
        "CheckoutResult",
        "<ns1:success>false</ns1:success><ns1:message>Превышен кредитный лимит</ns1:message>",
    )
    with pytest.raises(OrderRejected, match="кредитный лимит"):
        run(supplier.place_order([OrderLine(offer, 1)], ""))


def test_order_needs_payment_and_contact(fake):
    supplier = RosskoSupplier(RosskoConfig(key1="a", key2="b", delivery_id="1"))
    offer = run(supplier.search("04465-33471"))[0]
    with pytest.raises(OrderRejected, match="ROSSKO_PAYMENT_ID"):
        run(supplier.place_order([OrderLine(offer, 1)], ""))


def test_order_statuses_show_delivery_date(fake):
    fake.responses["GetOrders"] = envelope(
        "GetOrders",
        "OrdersResult",
        "<ns1:success>true</ns1:success><ns1:OrdersList><ns1:Order><ns1:id>7001</ns1:id>"
        "<ns1:created_date>2026-11-17</ns1:created_date>"
        "<ns1:delivery_date>2026-11-19</ns1:delivery_date>"
        "<ns1:total_price>77000</ns1:total_price><ns1:extra>0</ns1:extra>"
        "<ns1:parts/></ns1:Order></ns1:OrdersList>",
    )
    statuses = run(RosskoSupplier(CONFIG).order_statuses(["7001", "7002"]))
    assert statuses == {"7001": "Доставка: 2026-11-19"}
    fields = body_of(fake.requests[-1][1])
    assert fields["order_ids"] == [{"id": ["7001", "7002"]}]


def test_full_bot_flow_with_rossko(fake, conn):
    """Мастер ищет → корзина → админ заказывает: весь путь через «Росско»."""
    from stobot.ai.dictionary import DictionaryRecognizer
    from stobot.catalog.stub import StubCatalog
    from stobot.core.app import BotApp
    from tests.conftest import ADMIN, MASTER, find_action

    app = BotApp(
        conn=conn,
        supplier=RosskoSupplier(CONFIG),
        recognizer=DictionaryRecognizer(),
        catalog=StubCatalog(),
        admin_ids=frozenset({ADMIN.id}),
        test_mode=False,
    )
    found = run(app.handle_text(MASTER, "04465-33471"))
    assert "38 500 ₸" in found.replies[0].text
    analogs = run(app.handle_action(MASTER, find_action(found, "an:")))
    assert "продаётся по 2 шт" in analogs.replies[0].text
    added = run(app.handle_action(MASTER, find_action(analogs, "add:")))
    assert "× 2" in added.replies[0].text  # кратность 2 — сразу 2 штуки

    fake.responses["GetCheckout"] = envelope(
        "GetCheckout",
        "CheckoutResult",
        "<ns1:success>true</ns1:success><ns1:OrderIDS><ns1:id>7001</ns1:id></ns1:OrderIDS>",
    )
    check = run(app.handle_action(ADMIN, "co"))
    done = run(app.handle_action(ADMIN, find_action(check, "co:ok:")))
    assert "7001" in done.replies[0].text
    assert app.cart.items() == []


def test_setup_wizard_fills_env(fake, tmp_path, monkeypatch):
    from dotenv import dotenv_values

    from stobot import rossko_setup

    fake.responses["GetCheckoutDetails"] = envelope(
        "GetCheckoutDetails",
        "CheckoutDetailsResult",
        "<ns1:success>true</ns1:success>"
        "<ns1:DeliveryType><ns1:delivery><ns1:id>000000001</ns1:id><ns1:name>Доставка</ns1:name>"
        "</ns1:delivery><ns1:delivery><ns1:id>000000002</ns1:id><ns1:name>Самовывоз</ns1:name>"
        "</ns1:delivery></ns1:DeliveryType>"
        "<ns1:PaymentType><ns1:payment><ns1:id>1</ns1:id><ns1:name>Безнал</ns1:name>"
        "</ns1:payment></ns1:PaymentType>"
        "<ns1:DeliveryAddress><ns1:address><ns1:id>55</ns1:id><ns1:city>Астана</ns1:city>"
        "<ns1:street>Сарыарка</ns1:street><ns1:Delivery><ns1:ids><ns1:id>000000001</ns1:id>"
        "</ns1:ids></ns1:Delivery></ns1:address></ns1:DeliveryAddress>",
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=x\nADMIN_IDS=1\nTEST_MODE=true\n")
    answers = iter(["KEY-1", "KEY-2", "1", "1", "Ерлан", "+77010000000"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert run(rossko_setup.main()) == 0
    env = dotenv_values(tmp_path / ".env")
    assert env["SUPPLIER"] == "rossko"
    assert (env["ROSSKO_KEY1"], env["ROSSKO_DELIVERY_ID"], env["ROSSKO_ADDRESS_ID"]) == (
        "KEY-1",
        "000000001",
        "55",
    )
    assert env["ROSSKO_PAYMENT_ID"] == "1"  # единственный вариант — выбран сам
    assert env["TELEGRAM_BOT_TOKEN"] == "x"  # остальное не тронуто
    assert env["TEST_MODE"] == "true"


def test_search_retries_once_but_order_never(monkeypatch):
    calls = []

    def flaky(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            raise httpx.ConnectError("обрыв")
        return httpx.Response(200, text=SEARCH_OK)

    monkeypatch.setattr(soap, "TRANSPORT", httpx.MockTransport(flaky))
    monkeypatch.setattr(soap.asyncio, "sleep", lambda s: _noop())
    offers = run(RosskoSupplier(CONFIG).search("04465-33471"))
    assert len(offers) == 1 and len(calls) == 2  # повторили и получили ответ

    calls.clear()

    def always_broken(request):
        calls.append(request.url.path)
        raise httpx.ConnectError("обрыв")

    monkeypatch.setattr(soap, "TRANSPORT", httpx.MockTransport(always_broken))
    with pytest.raises(SupplierUnavailable):
        run(RosskoSupplier(CONFIG).place_order([OrderLine(offers[0], 1)], ""))
    assert len(calls) == 1  # заказ не повторяем — чтобы не было двух заказов


async def _noop():
    return None


def test_bot_shows_clear_message_on_bad_keys(fake, conn):
    from stobot.ai.dictionary import DictionaryRecognizer
    from stobot.catalog.stub import StubCatalog
    from stobot.core.app import BotApp
    from tests.conftest import ADMIN, MASTER

    fake.responses["GetSearch"] = envelope(
        "GetSearch",
        "SearchResult",
        "<ns1:success>false</ns1:success><ns1:message>Неверный KEY1 и/или KEY2</ns1:message>",
    )
    app = BotApp(
        conn=conn,
        supplier=RosskoSupplier(CONFIG),
        recognizer=DictionaryRecognizer(),
        catalog=StubCatalog(),
        admin_ids=frozenset({ADMIN.id}),
        test_mode=True,
    )
    response = run(app.handle_text(MASTER, "04465-33471"))
    assert "Неверный KEY1" in response.replies[0].text
