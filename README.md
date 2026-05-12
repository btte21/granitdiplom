# granitdiplom

## Granit-Ural AIS

Centralized Flask/PostgreSQL web application for order intake, stock reservation, warehouse distribution, and audit visibility inside the Granit-Ural operating model.

## Stack

- Backend: Python 3.x + Flask
- Database: PostgreSQL managed through pgAdmin 4
- Frontend: HTML5, Bootstrap 5, vanilla JavaScript
- Testing: pytest

## Functional Scope

- Order management with manual web-form entry and REST-style API endpoints
- Automatic stock reservation at order creation to prevent overselling
- Warehouse dashboard for picking, packing, and shipping progression
- Role-based access control:
  - `ADMIN`: full access, including audit view
  - `MANAGER`: orders, priorities, shipping assignments, reports
  - `WAREHOUSE`: stock and shipping execution
- Audit trail driven by PostgreSQL triggers

## Project Structure

```text
app/
  __init__.py
  api.py
  auth.py
  config.py
  passwords.py
  repository.py
  routes.py
  security.py
  services.py
  static/
  templates/
sql/
  01_schema.sql
  02_seed.sql
  03_pgadmin_usage.sql
tests/
run.py
requirements.txt
```

## Database Assembly Guide (pgAdmin 4)

1. Open pgAdmin 4 and create a database named `granit_ural_ais`.
2. Open the Query Tool for that database.
3. Execute [sql/01_schema.sql](C:/Users/Pavl/Documents/New%20project/sql/01_schema.sql) to create tables, enums, constraints, triggers, indexes, and the `v_inventory_status` view.
4. Execute [sql/02_seed.sql](C:/Users/Pavl/Documents/New%20project/sql/02_seed.sql) to load baseline users, catalog items, and warehouse balances.
5. Optionally execute queries from [sql/03_pgadmin_usage.sql](C:/Users/Pavl/Documents/New%20project/sql/03_pgadmin_usage.sql) for day-to-day inspection and controlled maintenance.

### Database Notes

- `warehouse_stocks` stores both `on_hand_qty` and `reserved_qty`.
- Reservation is enforced in backend transactions using row-level locks (`FOR UPDATE`) before stock changes are written.
- Audit capture is automatic for `users`, `products`, `warehouse_stocks`, `orders`, `order_items`, and `shipping_tasks`.
- To attribute direct pgAdmin updates to a specific user, set `app.user_id` in the session transaction before running manual `UPDATE` statements.

## Application Assembly Guide

1. Create a virtual environment:

```powershell
python -m venv .venv
```

2. Activate it:

```powershell
.venv\Scripts\activate
```

3. Install dependencies:

```powershell
pip install -r requirements.txt
```

4. Copy `.env.example` to `.env` and set the PostgreSQL connection string:

```env
FLASK_SECRET_KEY=change-me
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/granit_ural_ais
APP_PORT=5005
```

If your local PostgreSQL password is not `postgres`, set the explicit fields too:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=granit_ural_ais
DB_USER=postgres
DB_PASSWORD=your_real_postgres_password
```

5. Launch the application:

```powershell
python run.py
```

6. Open `http://127.0.0.1:5005`.

### Seeded Accounts

- `admin@granit-ural.local` / `AdminPass123!`
- `manager@granit-ural.local` / `ManagerPass123!`
- `warehouse@granit-ural.local` / `WarehousePass123!`

## Feature-by-Feature Verification Guide

### 1. Order Management

1. Sign in as `MANAGER`.
2. Open `/orders`.
3. Create a new order with one or more products.
4. Confirm the order appears in the register and receives status `RESERVED`.

### 2. Auto-Reservation

1. Before creating an order, check product availability on `/products`.
2. Submit an order for that product.
3. Return to `/products` and verify `reserved_qty` increased and `available_qty` decreased instantly.
4. Try to order beyond available stock through the form or `POST /api/orders`; the request should fail.

### 3. Distribution Dashboard

1. Open `/dashboard`.
2. As `MANAGER`, update an order priority and assign the shipping task to a warehouse user.
3. As `WAREHOUSE`, open `/warehouse` and move the order through `PROCESSING`, `READY_TO_SHIP`, and `SHIPPED`.

### 4. RBAC

1. `ADMIN` should access all screens, including `/audit`.
2. `MANAGER` should create orders and change priorities, but not access admin-only audit data.
3. `WAREHOUSE` should access stock and task views, but receive `403` when attempting manager-only order creation.

### 5. Audit Logs

1. Create or update an order.
2. Sign in as `ADMIN`.
3. Open `/audit`.
4. Confirm that inserts and updates for orders, line items, stock, and shipping tasks appear in the log.

## REST Endpoints

- `GET /api/products`
- `GET /api/orders`
- `GET /api/orders/<id>`
- `POST /api/orders`
- `PATCH /api/orders/<id>/status`
- `PATCH /api/orders/<id>/priority`
- `GET /api/dashboard/tasks`

## Testing Guide

1. Activate the virtual environment.
2. Run:

```powershell
pytest
```

### Covered Scenarios

- Successful stock reservation on order creation
- Stock release on cancellation
- Stock consumption on shipping
- Invalid order status transitions
- RBAC protection for manager, warehouse, and admin routes
- API order creation and status progression

## Operational Notes

- The Flask launcher uses port `5005` by default to avoid Windows `WinError 10013` conflicts commonly seen on port `5000`.
- The repository layer uses parameterized SQL only.
- For production rollout, place the Flask app behind a WSGI server and replace the development secret key with a strong random value.
