import pytest

from app.services import InvalidStatusTransitionError


def login_as(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_manager_can_access_order_dashboard(client):
    response = login_as(client, "manager@granit-ural.local", "ManagerPass123!")
    assert response.status_code == 200
    assert "Панель управления распределением".encode("utf-8") in response.data


def test_warehouse_cannot_create_order(client):
    login_as(client, "warehouse@granit-ural.local", "WarehousePass123!")

    response = client.post(
        "/api/orders",
        json={
            "order_number": "GU-2026-005",
            "customer_name": "OOO Restrict",
            "customer_email": "ops@restrict.example",
            "customer_phone": "+7-343-000-50-50",
            "priority": 3,
            "items": [{"product_id": 2, "quantity": 1}],
        },
    )

    assert response.status_code == 403


def test_warehouse_can_access_warehouse_view_but_not_audit(client):
    login_as(client, "warehouse@granit-ural.local", "WarehousePass123!")

    warehouse_response = client.get("/warehouse")
    audit_response = client.get("/audit")

    assert warehouse_response.status_code == 200
    assert "Складские задачи по отгрузке".encode("utf-8") in warehouse_response.data
    assert audit_response.status_code == 403


def test_invalid_status_transition_is_rejected(repository):
    order = repository.create_order(
        {
            "order_number": "GU-2026-006",
            "customer_name": "OOO Invalid",
            "customer_email": "bad@invalid.example",
            "customer_phone": "+7-343-000-60-60",
            "priority": 5,
            "items": [{"product_id": 1, "quantity": 1}],
        },
        actor_id=2,
    )

    with pytest.raises(InvalidStatusTransitionError, match="Невозможно сменить статус заказа"):
        repository.update_order_status(order["id"], "SHIPPED", actor_id=3)
