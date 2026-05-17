import pytest
from unittest.mock import MagicMock
from app.yandex_market_service import YandexMarketService
from app.repository import InMemoryRepository

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
    # Setup mock response
    mock_client.get_orders.return_value = {
        "orders": [
            {
                "id": 12345,
                "status": "PROCESSING",
                "buyer": {
                    "firstName": "Иван",
                    "lastName": "Иванов",
                    "email": "ivan@example.com",
                    "phone": "+79001112233"
                },
                "items": [
                    {
                        "offerId": "GU-SRV-001",
                        "count": 2,
                        "price": 240000
                    }
                ]
            }
        ]
    }

    # Initial state
    assert repository.get_order_by_number("YM-12345") is None

    # Process
    res = service.fetch_and_process_orders()

    # Verify
    assert res["fetched"] == 1
    assert res["created"] == 1

    order = repository.get_order_by_number("YM-12345")
    assert order is not None
    assert order["customer_name"] == "Иванов Иван"
    assert len(order["items"]) == 1
    assert order["items"][0]["sku"] == "GU-SRV-001"
    assert order["items"][0]["quantity"] == 2

def test_fetch_and_process_orders_skips_existing(service, repository, mock_client):
    # Pre-create order
    repository.create_order({
        "order_number": "YM-12345",
        "customer_name": "Existing",
        "customer_email": "test@test.com",
        "customer_phone": "123",
        "items": [{"product_id": 1, "quantity": 1}]
    }, actor_id=1)

    mock_client.get_orders.return_value = {
        "orders": [{"id": 12345}]
    }

    res = service.fetch_and_process_orders()
    assert res["skipped"] == 1
    assert res["created"] == 0

def test_fetch_and_process_orders_handles_missing_product(service, repository, mock_client):
    mock_client.get_orders.return_value = {
        "orders": [
            {
                "id": 67890,
                "items": [{"offerId": "NON-EXISTENT", "count": 1}]
            }
        ]
    }

    res = service.fetch_and_process_orders()
    assert res["errors"] == 1
    assert res["created"] == 0
    assert repository.get_order_by_number("YM-67890") is None
