def login_as(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_order_creation_reserves_stock(repository):
    order = repository.create_order(
        {
            "order_number": "GU-2026-001",
            "customer_name": "OOO Vector",
            "customer_email": "procurement@vector.example",
            "customer_phone": "+7-343-000-10-10",
            "priority": 2,
            "items": [{"product_id": 2, "quantity": 5}],
        },
        actor_id=2,
    )

    product = repository.get_product_by_id(2)
    assert order["status"] == "RESERVED"
    assert product["reserved_qty"] == 5
    assert product["available_qty"] == 20
    assert order["shipping_task"]["status"] == "PENDING"


def test_order_status_transition_to_shipped_consumes_reserved_stock(repository):
    order = repository.create_order(
        {
            "order_number": "GU-2026-002",
            "customer_name": "ZAO Delta",
            "customer_email": "ops@delta.example",
            "customer_phone": "+7-343-000-20-20",
            "priority": 1,
            "items": [{"product_id": 1, "quantity": 3}],
        },
        actor_id=2,
    )

    repository.update_order_status(order["id"], "PROCESSING", actor_id=3)
    repository.update_order_status(order["id"], "READY_TO_SHIP", actor_id=3)
    repository.update_order_status(order["id"], "SHIPPED", actor_id=3)

    product = repository.get_product_by_id(1)
    updated_order = repository.get_order(order["id"])
    assert updated_order["status"] == "SHIPPED"
    assert updated_order["shipping_task"]["status"] == "COMPLETED"
    assert product["on_hand_qty"] == 7
    assert product["reserved_qty"] == 2


def test_order_cancellation_releases_reserved_stock(repository):
    order = repository.create_order(
        {
            "order_number": "GU-2026-003",
            "customer_name": "IP Novikov",
            "customer_email": "buyer@novikov.example",
            "customer_phone": "+7-343-000-30-30",
            "priority": 4,
            "items": [{"product_id": 3, "quantity": 2}],
        },
        actor_id=2,
    )

    repository.update_order_status(order["id"], "CANCELLED", actor_id=2)

    product = repository.get_product_by_id(3)
    updated_order = repository.get_order(order["id"])
    assert updated_order["status"] == "CANCELLED"
    assert updated_order["shipping_task"]["status"] == "CANCELLED"
    assert product["reserved_qty"] == 1
    assert all(item["reserved_qty"] == 0 for item in updated_order["items"])


def test_api_order_creation_and_status_progression(client, repository):
    login_as(client, "manager@granit-ural.local", "ManagerPass123!")

    create_response = client.post(
        "/api/orders",
        json={
            "order_number": "GU-2026-004",
            "customer_name": "OOO Signal",
            "customer_email": "sales@signal.example",
            "customer_phone": "+7-343-000-40-40",
            "priority": 2,
            "items": [{"product_id": 2, "quantity": 4}],
        },
    )
    assert create_response.status_code == 201
    order_id = create_response.get_json()["id"]

    processing_response = client.patch(f"/api/orders/{order_id}/status", json={"status": "PROCESSING"})
    ready_response = client.patch(f"/api/orders/{order_id}/status", json={"status": "READY_TO_SHIP"})
    shipped_response = client.patch(f"/api/orders/{order_id}/status", json={"status": "SHIPPED"})

    assert processing_response.status_code == 200
    assert ready_response.status_code == 200
    assert shipped_response.status_code == 200
    assert repository.get_order(order_id)["status"] == "SHIPPED"
