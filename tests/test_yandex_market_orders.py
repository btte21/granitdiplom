import pytest
from unittest.mock import MagicMock

from app.repository import InMemoryRepository
from app.yandex_market_service import YandexMarketService


@pytest.fixture
def repository():
    return InMemoryRepository()


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def service(mock_client, repository):
    return YandexMarketService(client=mock_client, repository=repository)


def test_fetch_and_process_orders_creates_new_order(service, repository, mock_client):
    mock_client.get_orders.return_value = {
        "result": {
            "orders": [
                {
                    "id": 12345,
                    "creationDate": "2026-05-21T10:00:00+05:00",
                    "status": "PROCESSING",
                    "buyer": {
                        "firstName": "Иван",
                        "lastName": "Иванов",
                        "email": "ivan@example.com",
                        "phone": "+79001112233",
                    },
                    "items": [
                        {
                            "offerId": "GU-SRV-001",
                            "count": 2,
                            "price": 240000,
                        }
                    ],
                }
            ]
        }
    }

    assert repository.get_order_by_number("YM-2026-05-21-12345") is None

    res = service.fetch_and_process_orders()

    assert res["fetched"] == 1
    assert res["created"] == 1

    order = repository.get_order_by_number("YM-2026-05-21-12345")
    assert order is not None
    assert order["customer_name"] == "Иванов Иван"
    assert len(order["items"]) == 1
    assert order["items"][0]["sku"] == "GU-SRV-001"
    assert order["items"][0]["quantity"] == 2
    assert order["items"][0]["reserved_qty"] == 0


def test_fetch_and_process_orders_skips_existing(service, repository, mock_client):
    repository.create_external_order(
        {
            "order_number": "YM-2026-05-21-12345",
            "customer_name": "Existing",
            "customer_email": "test@test.com",
            "customer_phone": "123",
            "items": [{"product_id": 1, "quantity": 1}],
        },
        actor_id=1,
    )

    mock_client.get_orders.return_value = {
        "result": {
            "orders": [
                {
                    "id": 12345,
                    "creationDate": "2026-05-21T10:00:00+05:00",
                }
            ]
        }
    }

    res = service.fetch_and_process_orders()
    assert res["skipped"] == 1
    assert res["created"] == 0


def test_fetch_and_process_orders_creates_placeholder_product_for_missing_sku(service, repository, mock_client):
    mock_client.get_orders.return_value = {
        "result": {
            "orders": [
                {
                    "id": 67890,
                    "creationDate": "2026-05-20T09:30:00+05:00",
                    "items": [
                        {
                            "offerId": "NON-EXISTENT",
                            "offerName": "Yandex Imported Product",
                            "count": 1,
                            "price": 999,
                        }
                    ],
                }
            ]
        }
    }

    res = service.fetch_and_process_orders()

    assert res["errors"] == 0
    assert res["created"] == 1
    product = repository.get_product_by_sku("NON-EXISTENT")
    assert product is not None
    assert product["name"] == "Yandex Imported Product"
    order = repository.get_order_by_number("YM-2026-05-20-67890")
    assert order is not None


def test_import_stocks_updates_local_balances(service, repository, mock_client):
    mock_client.get_stocks.return_value = {
        "result": {
            "warehouses": [
                {
                    "warehouseId": 2058655,
                    "offers": [
                        {
                            "offerId": "GU-SRV-001",
                            "stocks": [
                                {"type": "FIT", "count": 7},
                                {"type": "FREEZE", "count": 2},
                            ],
                        },
                        {
                            "offerId": "MRKT-NEW-001",
                            "stocks": [
                                {"type": "AVAILABLE", "count": 5},
                                {"type": "FREEZE", "count": 1},
                            ],
                        },
                    ],
                }
            ]
        }
    }

    res = service.import_stocks(stocks_warehouse_id=2058655)

    assert res["fetched"] == 2
    assert res["sku_count"] == 2
    assert res["products_created"] == 1
    existing_product = repository.get_product_by_sku("GU-SRV-001")
    assert existing_product["on_hand_qty"] == 7
    assert existing_product["reserved_qty"] == 2
    created_product = repository.get_product_by_sku("MRKT-NEW-001")
    assert created_product is not None
    assert created_product["on_hand_qty"] == 6
    assert created_product["reserved_qty"] == 1
