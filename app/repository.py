from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import unquote, urlparse

import psycopg2
from psycopg2.extras import RealDictCursor

from .passwords import hash_password, verify_password
from .services import DatabaseConnectionError, InsufficientStockError, InvalidStatusTransitionError, ValidationError


ALLOWED_ORDER_TRANSITIONS = {
    "RESERVED": {"PROCESSING", "CANCELLED"},
    "PROCESSING": {"READY_TO_SHIP", "CANCELLED"},
    "READY_TO_SHIP": {"SHIPPED", "CANCELLED"},
    "SHIPPED": set(),
    "CANCELLED": set(),
}


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


def normalize_order_items(items: list[dict[str, Any]]):
    aggregated = {}
    for item in items:
        product_id = int(item["product_id"])
        quantity = int(item["quantity"])
        if product_id not in aggregated:
            aggregated[product_id] = {"product_id": product_id, "quantity": 0}
        aggregated[product_id]["quantity"] += quantity
    return list(aggregated.values())


@dataclass
class RepositorySummary:
    total_orders: int
    reserved_orders: int
    ready_to_ship_orders: int
    low_stock_items: int


class PostgresRepository:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _connect(self):
        try:
            return psycopg2.connect(**self._connection_kwargs())
        except UnicodeDecodeError as exc:
            raise DatabaseConnectionError(self._database_help_message()) from exc
        except psycopg2.Error as exc:
            raise DatabaseConnectionError(self._database_help_message()) from exc

    def _connection_kwargs(self):
        parsed = urlparse(self.dsn)
        if parsed.scheme not in {"postgresql", "postgres"}:
            raise DatabaseConnectionError(
                "Unsupported DATABASE_URL format. Use postgresql://user:password@host:port/database"
            )

        dbname = unquote(parsed.path.lstrip("/")) or "postgres"
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
            "dbname": dbname,
            "user": unquote(parsed.username or "postgres"),
            "password": unquote(parsed.password or ""),
            "client_encoding": "UTF8",
        }

    def _database_help_message(self):
        params = self._connection_kwargs()
        return (
            "Could not connect to PostgreSQL. "
            f"Target: {params['user']}@{params['host']}:{params['port']}/{params['dbname']}. "
            "Check that PostgreSQL is running, the database exists, and your DB_USER/DB_PASSWORD "
            "or DATABASE_URL values are correct in .env."
        )

    @contextmanager
    def _connection(self, actor_id=None):
        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if actor_id is not None:
                    cursor.execute("SELECT set_config('app.user_id', %s, TRUE)", (str(actor_id),))
                yield conn, cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _row(self, cursor):
        row = cursor.fetchone()
        return dict(row) if row else None

    def authenticate_user(self, email: str, password: str):
        with self._connection() as (_, cursor):
            cursor.execute(
                """
                SELECT id, full_name, email, password_hash, role, is_active
                FROM users
                WHERE lower(email) = lower(%s)
                """,
                (email,),
            )
            user = self._row(cursor)
            if not user or not user["is_active"]:
                return None
            if not verify_password(password, user["password_hash"]):
                return None
            user.pop("password_hash", None)
            return user

    def get_user_by_id(self, user_id: int):
        with self._connection() as (_, cursor):
            cursor.execute(
                """
                SELECT id, full_name, email, role, is_active
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )
            return self._row(cursor)

    def list_users_by_role(self, role: str):
        with self._connection() as (_, cursor):
            cursor.execute(
                """
                SELECT id, full_name, email, role
                FROM users
                WHERE role = %s AND is_active = TRUE
                ORDER BY full_name
                """,
                (role,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def list_products_with_stock(self):
        with self._connection() as (_, cursor):
            cursor.execute(
                """
                SELECT
                    p.id,
                    p.sku,
                    p.name,
                    p.technical_specs,
                    p.unit_price,
                    COALESCE(ws.on_hand_qty, 0) AS on_hand_qty,
                    COALESCE(ws.reserved_qty, 0) AS reserved_qty,
                    COALESCE(ws.on_hand_qty, 0) - COALESCE(ws.reserved_qty, 0) AS available_qty
                FROM products p
                LEFT JOIN warehouse_stocks ws ON ws.product_id = p.id
                WHERE p.is_active = TRUE
                ORDER BY p.name
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_product_by_id(self, product_id: int):
        with self._connection() as (_, cursor):
            cursor.execute(
                """
                SELECT
                    p.id,
                    p.sku,
                    p.name,
                    p.technical_specs,
                    p.unit_price,
                    COALESCE(ws.on_hand_qty, 0) AS on_hand_qty,
                    COALESCE(ws.reserved_qty, 0) AS reserved_qty,
                    COALESCE(ws.on_hand_qty, 0) - COALESCE(ws.reserved_qty, 0) AS available_qty
                FROM products p
                LEFT JOIN warehouse_stocks ws ON ws.product_id = p.id
                WHERE p.id = %s
                """,
                (product_id,),
            )
            return self._row(cursor)

    def list_orders(self):
        with self._connection() as (_, cursor):
            cursor.execute(
                """
                SELECT
                    o.id,
                    o.order_number,
                    o.customer_name,
                    o.customer_email,
                    o.customer_phone,
                    o.status,
                    o.priority,
                    o.notes,
                    o.created_at,
                    o.updated_at,
                    COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS total_amount
                FROM orders o
                LEFT JOIN order_items oi ON oi.order_id = o.id
                GROUP BY o.id
                ORDER BY o.created_at DESC, o.id DESC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_order(self, order_id: int):
        with self._connection() as (_, cursor):
            cursor.execute(
                """
                SELECT
                    o.id,
                    o.order_number,
                    o.customer_name,
                    o.customer_email,
                    o.customer_phone,
                    o.status,
                    o.priority,
                    o.notes,
                    o.created_at,
                    o.updated_at
                FROM orders o
                WHERE o.id = %s
                """,
                (order_id,),
            )
            order = self._row(cursor)
            if not order:
                return None
            cursor.execute(
                """
                SELECT
                    oi.id,
                    oi.product_id,
                    p.sku,
                    p.name AS product_name,
                    oi.quantity,
                    oi.unit_price,
                    oi.reserved_qty
                FROM order_items oi
                INNER JOIN products p ON p.id = oi.product_id
                WHERE oi.order_id = %s
                ORDER BY oi.id
                """,
                (order_id,),
            )
            order["items"] = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT id, order_id, assigned_to, status, priority, due_date, created_at, updated_at
                FROM shipping_tasks
                WHERE order_id = %s
                """,
                (order_id,),
            )
            order["shipping_task"] = self._row(cursor)
            return order

    def create_order(self, payload: dict[str, Any], actor_id: int):
        self._validate_order_payload(payload)
        payload = {**payload, "items": normalize_order_items(payload["items"])}
        with self._connection(actor_id=actor_id) as (_, cursor):
            cursor.execute(
                """
                INSERT INTO orders (
                    order_number,
                    customer_name,
                    customer_email,
                    customer_phone,
                    status,
                    priority,
                    notes,
                    created_by
                )
                VALUES (%s, %s, %s, %s, 'RESERVED', %s, %s, %s)
                RETURNING id, order_number, status, priority, customer_name, customer_email, customer_phone, notes, created_at, updated_at
                """,
                (
                    payload["order_number"],
                    payload["customer_name"],
                    payload["customer_email"],
                    payload["customer_phone"],
                    payload.get("priority", 3),
                    payload.get("notes"),
                    actor_id,
                ),
            )
            order = self._row(cursor)

            for item in payload["items"]:
                cursor.execute(
                    """
                    SELECT
                        p.id,
                        p.unit_price,
                        ws.on_hand_qty,
                        ws.reserved_qty
                    FROM products p
                    INNER JOIN warehouse_stocks ws ON ws.product_id = p.id
                    WHERE p.id = %s
                    FOR UPDATE
                    """,
                    (item["product_id"],),
                )
                stock = self._row(cursor)
                if not stock:
                    raise ValidationError(f"Product {item['product_id']} is not available in stock.")
                available_qty = stock["on_hand_qty"] - stock["reserved_qty"]
                if available_qty < item["quantity"]:
                    raise InsufficientStockError(
                        f"Insufficient stock for product {item['product_id']}. Requested {item['quantity']}, available {available_qty}."
                    )

                cursor.execute(
                    """
                    UPDATE warehouse_stocks
                    SET reserved_qty = reserved_qty + %s
                    WHERE product_id = %s
                    """,
                    (item["quantity"], item["product_id"]),
                )
                cursor.execute(
                    """
                    INSERT INTO order_items (order_id, product_id, quantity, unit_price, reserved_qty)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        order["id"],
                        item["product_id"],
                        item["quantity"],
                        item.get("unit_price", stock["unit_price"]),
                        item["quantity"],
                    ),
                )

            cursor.execute(
                """
                INSERT INTO shipping_tasks (order_id, status, priority, due_date)
                VALUES (%s, 'PENDING', %s, CURRENT_DATE + INTERVAL '1 day')
                RETURNING id, order_id, assigned_to, status, priority, due_date, created_at, updated_at
                """,
                (order["id"], order["priority"]),
            )
            order["shipping_task"] = self._row(cursor)
            cursor.execute(
                """
                SELECT
                    oi.id,
                    oi.product_id,
                    p.sku,
                    p.name AS product_name,
                    oi.quantity,
                    oi.unit_price,
                    oi.reserved_qty
                FROM order_items oi
                INNER JOIN products p ON p.id = oi.product_id
                WHERE oi.order_id = %s
                ORDER BY oi.id
                """,
                (order["id"],),
            )
            order["items"] = [dict(row) for row in cursor.fetchall()]
            return order

    def update_order_status(self, order_id: int, new_status: str, actor_id: int):
        with self._connection(actor_id=actor_id) as (_, cursor):
            cursor.execute(
                "SELECT id, status FROM orders WHERE id = %s FOR UPDATE",
                (order_id,),
            )
            order = self._row(cursor)
            if not order:
                raise ValidationError("Order not found.")

            current_status = order["status"]
            if new_status not in ALLOWED_ORDER_TRANSITIONS.get(current_status, set()):
                raise InvalidStatusTransitionError(
                    f"Cannot move order {order_id} from {current_status} to {new_status}."
                )

            cursor.execute(
                """
                SELECT product_id, reserved_qty
                FROM order_items
                WHERE order_id = %s
                FOR UPDATE
                """,
                (order_id,),
            )
            items = [dict(row) for row in cursor.fetchall()]

            if new_status == "CANCELLED":
                for item in items:
                    cursor.execute(
                        """
                        UPDATE warehouse_stocks
                        SET reserved_qty = reserved_qty - %s
                        WHERE product_id = %s
                        """,
                        (item["reserved_qty"], item["product_id"]),
                    )
                cursor.execute(
                    "UPDATE order_items SET reserved_qty = 0 WHERE order_id = %s",
                    (order_id,),
                )
            elif new_status == "SHIPPED":
                for item in items:
                    cursor.execute(
                        """
                        UPDATE warehouse_stocks
                        SET
                            on_hand_qty = on_hand_qty - %s,
                            reserved_qty = reserved_qty - %s
                        WHERE product_id = %s
                        """,
                        (item["reserved_qty"], item["reserved_qty"], item["product_id"]),
                    )
                cursor.execute(
                    "UPDATE order_items SET reserved_qty = 0 WHERE order_id = %s",
                    (order_id,),
                )

            cursor.execute(
                "UPDATE orders SET status = %s WHERE id = %s",
                (new_status, order_id),
            )

            task_status = {
                "PROCESSING": "PICKING",
                "READY_TO_SHIP": "PACKED",
                "SHIPPED": "COMPLETED",
                "CANCELLED": "CANCELLED",
            }.get(new_status)
            if task_status:
                cursor.execute(
                    "UPDATE shipping_tasks SET status = %s WHERE order_id = %s",
                    (task_status, order_id),
                )

        return self.get_order(order_id)

    def update_order_priority(self, order_id: int, priority: int, actor_id: int):
        if priority < 1 or priority > 5:
            raise ValidationError("Priority must be between 1 and 5.")
        with self._connection(actor_id=actor_id) as (_, cursor):
            cursor.execute(
                "UPDATE orders SET priority = %s WHERE id = %s RETURNING id",
                (priority, order_id),
            )
            if not cursor.fetchone():
                raise ValidationError("Order not found.")
            cursor.execute(
                "UPDATE shipping_tasks SET priority = %s WHERE order_id = %s",
                (priority, order_id),
            )
        return self.get_order(order_id)

    def assign_shipping_task(self, task_id: int, assigned_to: int, actor_id: int):
        with self._connection(actor_id=actor_id) as (_, cursor):
            cursor.execute(
                """
                UPDATE shipping_tasks
                SET assigned_to = %s
                WHERE id = %s
                RETURNING id
                """,
                (assigned_to, task_id),
            )
            if not cursor.fetchone():
                raise ValidationError("Shipping task not found.")
        return self.list_shipping_tasks()

    def list_shipping_tasks(self):
        with self._connection() as (_, cursor):
            cursor.execute(
                """
                SELECT
                    st.id,
                    st.order_id,
                    st.assigned_to,
                    u.full_name AS assigned_to_name,
                    st.status,
                    st.priority,
                    st.due_date,
                    st.created_at,
                    st.updated_at,
                    o.order_number,
                    o.customer_name
                FROM shipping_tasks st
                INNER JOIN orders o ON o.id = st.order_id
                LEFT JOIN users u ON u.id = st.assigned_to
                ORDER BY st.priority ASC, st.created_at ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def list_audit_logs(self, limit: int = 100):
        with self._connection() as (_, cursor):
            cursor.execute(
                """
                SELECT
                    al.id,
                    al.table_name,
                    al.record_id,
                    al.action,
                    al.changed_by,
                    u.full_name AS changed_by_name,
                    al.details,
                    al.created_at
                FROM audit_logs al
                LEFT JOIN users u ON u.id = al.changed_by
                ORDER BY al.created_at DESC, al.id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_dashboard_summary(self):
        with self._connection() as (_, cursor):
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total_orders,
                    COUNT(*) FILTER (WHERE status = 'RESERVED') AS reserved_orders,
                    COUNT(*) FILTER (WHERE status = 'READY_TO_SHIP') AS ready_to_ship_orders
                FROM orders
                """
            )
            counts = self._row(cursor) or {}
            cursor.execute(
                """
                SELECT COUNT(*) AS low_stock_items
                FROM warehouse_stocks
                WHERE on_hand_qty - reserved_qty <= 5
                """
            )
            low_stock_row = self._row(cursor) or {"low_stock_items": 0}
            return {
                "total_orders": counts.get("total_orders", 0),
                "reserved_orders": counts.get("reserved_orders", 0),
                "ready_to_ship_orders": counts.get("ready_to_ship_orders", 0),
                "low_stock_items": low_stock_row["low_stock_items"],
            }

    def _validate_order_payload(self, payload: dict[str, Any]):
        required_fields = ("order_number", "customer_name", "customer_email", "customer_phone", "items")
        missing = [field for field in required_fields if not payload.get(field)]
        if missing:
            raise ValidationError(f"Missing required fields: {', '.join(missing)}")
        if not isinstance(payload["items"], list) or not payload["items"]:
            raise ValidationError("At least one order item is required.")
        for item in payload["items"]:
            if int(item["quantity"]) <= 0:
                raise ValidationError("Item quantity must be greater than zero.")


class InMemoryRepository:
    def __init__(self):
        self.users = {
            1: {
                "id": 1,
                "full_name": "System Administrator",
                "email": "admin@granit-ural.local",
                "password_hash": hash_password("AdminPass123!"),
                "role": "ADMIN",
                "is_active": True,
            },
            2: {
                "id": 2,
                "full_name": "Distribution Manager",
                "email": "manager@granit-ural.local",
                "password_hash": hash_password("ManagerPass123!"),
                "role": "MANAGER",
                "is_active": True,
            },
            3: {
                "id": 3,
                "full_name": "Warehouse Operator",
                "email": "warehouse@granit-ural.local",
                "password_hash": hash_password("WarehousePass123!"),
                "role": "WAREHOUSE",
                "is_active": True,
            },
        }
        self.products = {
            1: {
                "id": 1,
                "sku": "GU-SRV-001",
                "name": "Rack Server 2U",
                "technical_specs": '{"cpu": "Xeon Silver", "ram": "64 GB"}',
                "unit_price": Decimal("250000.00"),
                "on_hand_qty": 10,
                "reserved_qty": 2,
            },
            2: {
                "id": 2,
                "sku": "GU-LIC-002",
                "name": "Endpoint Security Suite",
                "technical_specs": '{"license_term": "12 months", "seats": 50}',
                "unit_price": Decimal("75000.00"),
                "on_hand_qty": 25,
                "reserved_qty": 0,
            },
            3: {
                "id": 3,
                "sku": "GU-NB-003",
                "name": "Business Notebook",
                "technical_specs": '{"cpu": "Core i7", "ram": "32 GB", "ssd": "1 TB"}',
                "unit_price": Decimal("98000.00"),
                "on_hand_qty": 8,
                "reserved_qty": 1,
            },
        }
        self.orders = {}
        self.order_items = {}
        self.shipping_tasks = {}
        self.audit_logs = []
        self._order_id = 1
        self._order_item_id = 1
        self._task_id = 1

    def authenticate_user(self, email: str, password: str):
        for user in self.users.values():
            if user["email"].lower() == email.lower() and user["is_active"]:
                if verify_password(password, user["password_hash"]):
                    safe_user = deepcopy(user)
                    safe_user.pop("password_hash", None)
                    return safe_user
        return None

    def get_user_by_id(self, user_id: int):
        user = self.users.get(user_id)
        if not user:
            return None
        safe_user = deepcopy(user)
        safe_user.pop("password_hash", None)
        return safe_user

    def list_users_by_role(self, role: str):
        users = []
        for user in self.users.values():
            if user["role"] == role and user["is_active"]:
                safe_user = deepcopy(user)
                safe_user.pop("password_hash", None)
                users.append(safe_user)
        return sorted(users, key=lambda item: item["full_name"])

    def list_products_with_stock(self):
        result = []
        for product in self.products.values():
            row = deepcopy(product)
            row["available_qty"] = row["on_hand_qty"] - row["reserved_qty"]
            result.append(row)
        return sorted(result, key=lambda item: item["name"])

    def get_product_by_id(self, product_id: int):
        product = self.products.get(product_id)
        if not product:
            return None
        row = deepcopy(product)
        row["available_qty"] = row["on_hand_qty"] - row["reserved_qty"]
        return row

    def list_orders(self):
        orders = list(self.orders.values())
        return sorted(orders, key=lambda order: order["id"], reverse=True)

    def get_order(self, order_id: int):
        order = self.orders.get(order_id)
        return deepcopy(order) if order else None

    def create_order(self, payload: dict[str, Any], actor_id: int):
        self._validate_order_payload(payload)
        payload = {**payload, "items": normalize_order_items(payload["items"])}
        order_id = self._order_id
        self._order_id += 1
        now = utcnow()
        items = []
        for item in payload["items"]:
            product = self.products.get(item["product_id"])
            if not product:
                raise ValidationError(f"Product {item['product_id']} not found.")
            available_qty = product["on_hand_qty"] - product["reserved_qty"]
            if available_qty < item["quantity"]:
                raise InsufficientStockError(
                    f"Insufficient stock for product {item['product_id']}. Requested {item['quantity']}, available {available_qty}."
                )

        for item in payload["items"]:
            product = self.products[item["product_id"]]
            product["reserved_qty"] += item["quantity"]
            order_item = {
                "id": self._order_item_id,
                "product_id": item["product_id"],
                "sku": product["sku"],
                "product_name": product["name"],
                "quantity": item["quantity"],
                "unit_price": item.get("unit_price", product["unit_price"]),
                "reserved_qty": item["quantity"],
            }
            self._order_item_id += 1
            items.append(order_item)
            self.order_items[order_item["id"]] = order_item

        task = {
            "id": self._task_id,
            "order_id": order_id,
            "assigned_to": None,
            "assigned_to_name": None,
            "status": "PENDING",
            "priority": payload.get("priority", 3),
            "due_date": now.date().isoformat(),
            "created_at": now.isoformat(sep=" "),
            "updated_at": now.isoformat(sep=" "),
            "order_number": payload["order_number"],
            "customer_name": payload["customer_name"],
        }
        self._task_id += 1
        self.shipping_tasks[task["id"]] = task

        order = {
            "id": order_id,
            "order_number": payload["order_number"],
            "customer_name": payload["customer_name"],
            "customer_email": payload["customer_email"],
            "customer_phone": payload["customer_phone"],
            "status": "RESERVED",
            "priority": payload.get("priority", 3),
            "notes": payload.get("notes", ""),
            "created_at": now.isoformat(sep=" "),
            "updated_at": now.isoformat(sep=" "),
            "items": items,
            "shipping_task": task,
        }
        order["total_amount"] = sum(item["quantity"] * item["unit_price"] for item in items)
        self.orders[order_id] = order
        self._log("orders", order_id, "INSERT", actor_id, {"status": "RESERVED", "order_number": payload["order_number"]})
        return deepcopy(order)

    def update_order_status(self, order_id: int, new_status: str, actor_id: int):
        order = self.orders.get(order_id)
        if not order:
            raise ValidationError("Order not found.")
        current_status = order["status"]
        if new_status not in ALLOWED_ORDER_TRANSITIONS.get(current_status, set()):
            raise InvalidStatusTransitionError(
                f"Cannot move order {order_id} from {current_status} to {new_status}."
            )
        if new_status == "CANCELLED":
            for item in order["items"]:
                self.products[item["product_id"]]["reserved_qty"] -= item["reserved_qty"]
                item["reserved_qty"] = 0
        elif new_status == "SHIPPED":
            for item in order["items"]:
                self.products[item["product_id"]]["on_hand_qty"] -= item["reserved_qty"]
                self.products[item["product_id"]]["reserved_qty"] -= item["reserved_qty"]
                item["reserved_qty"] = 0
        order["status"] = new_status
        order["updated_at"] = utcnow().isoformat(sep=" ")
        task_status = {
            "PROCESSING": "PICKING",
            "READY_TO_SHIP": "PACKED",
            "SHIPPED": "COMPLETED",
            "CANCELLED": "CANCELLED",
        }.get(new_status)
        if task_status:
            order["shipping_task"]["status"] = task_status
            order["shipping_task"]["updated_at"] = utcnow().isoformat(sep=" ")
            self.shipping_tasks[order["shipping_task"]["id"]] = deepcopy(order["shipping_task"])
        self._log("orders", order_id, "UPDATE", actor_id, {"status": new_status})
        return deepcopy(order)

    def update_order_priority(self, order_id: int, priority: int, actor_id: int):
        if priority < 1 or priority > 5:
            raise ValidationError("Priority must be between 1 and 5.")
        order = self.orders.get(order_id)
        if not order:
            raise ValidationError("Order not found.")
        order["priority"] = priority
        order["shipping_task"]["priority"] = priority
        order["updated_at"] = utcnow().isoformat(sep=" ")
        order["shipping_task"]["updated_at"] = order["updated_at"]
        self.shipping_tasks[order["shipping_task"]["id"]] = deepcopy(order["shipping_task"])
        self._log("orders", order_id, "UPDATE", actor_id, {"priority": priority})
        return deepcopy(order)

    def assign_shipping_task(self, task_id: int, assigned_to: int, actor_id: int):
        task = self.shipping_tasks.get(task_id)
        user = self.users.get(assigned_to)
        if not task or not user:
            raise ValidationError("Task or assignee not found.")
        task["assigned_to"] = assigned_to
        task["assigned_to_name"] = user["full_name"]
        task["updated_at"] = utcnow().isoformat(sep=" ")
        order = self.orders[task["order_id"]]
        order["shipping_task"] = deepcopy(task)
        self._log("shipping_tasks", task_id, "UPDATE", actor_id, {"assigned_to": assigned_to})
        return self.list_shipping_tasks()

    def list_shipping_tasks(self):
        tasks = list(self.shipping_tasks.values())
        return sorted(tasks, key=lambda task: (task["priority"], task["id"]))

    def list_audit_logs(self, limit: int = 100):
        return list(reversed(self.audit_logs[-limit:]))

    def get_dashboard_summary(self):
        total_orders = len(self.orders)
        reserved_orders = sum(1 for order in self.orders.values() if order["status"] == "RESERVED")
        ready_to_ship_orders = sum(1 for order in self.orders.values() if order["status"] == "READY_TO_SHIP")
        low_stock_items = sum(
            1 for product in self.products.values() if product["on_hand_qty"] - product["reserved_qty"] <= 5
        )
        return {
            "total_orders": total_orders,
            "reserved_orders": reserved_orders,
            "ready_to_ship_orders": ready_to_ship_orders,
            "low_stock_items": low_stock_items,
        }

    def _validate_order_payload(self, payload: dict[str, Any]):
        required_fields = ("order_number", "customer_name", "customer_email", "customer_phone", "items")
        missing = [field for field in required_fields if not payload.get(field)]
        if missing:
            raise ValidationError(f"Missing required fields: {', '.join(missing)}")
        if not isinstance(payload["items"], list) or not payload["items"]:
            raise ValidationError("At least one order item is required.")
        for item in payload["items"]:
            if int(item["quantity"]) <= 0:
                raise ValidationError("Item quantity must be greater than zero.")

    def _log(self, table_name: str, record_id: int, action: str, changed_by: int, details: dict[str, Any]):
        self.audit_logs.append(
            {
                "id": len(self.audit_logs) + 1,
                "table_name": table_name,
                "record_id": record_id,
                "action": action,
                "changed_by": changed_by,
                "changed_by_name": self.users.get(changed_by, {}).get("full_name"),
                "details": deepcopy(details),
                "created_at": utcnow().isoformat(sep=" "),
            }
        )
