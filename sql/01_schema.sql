BEGIN;

CREATE TYPE user_role AS ENUM ('ADMIN', 'MANAGER', 'WAREHOUSE');
CREATE TYPE order_status AS ENUM ('RESERVED', 'PROCESSING', 'READY_TO_SHIP', 'SHIPPED', 'CANCELLED');
CREATE TYPE shipping_task_status AS ENUM ('PENDING', 'PICKING', 'PACKED', 'COMPLETED', 'CANCELLED');

CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role user_role NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE products (
    id BIGSERIAL PRIMARY KEY,
    sku VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    technical_specs JSONB NOT NULL DEFAULT '{}'::jsonb,
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE warehouse_stocks (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL UNIQUE REFERENCES products(id) ON DELETE CASCADE,
    on_hand_qty INTEGER NOT NULL CHECK (on_hand_qty >= 0),
    reserved_qty INTEGER NOT NULL DEFAULT 0 CHECK (reserved_qty >= 0 AND reserved_qty <= on_hand_qty),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    order_number VARCHAR(50) NOT NULL UNIQUE,
    customer_name VARCHAR(255) NOT NULL,
    customer_email VARCHAR(255) NOT NULL,
    customer_phone VARCHAR(50) NOT NULL,
    status order_status NOT NULL DEFAULT 'RESERVED',
    priority SMALLINT NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    notes TEXT,
    created_by BIGINT REFERENCES users(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE order_items (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    reserved_qty INTEGER NOT NULL DEFAULT 0 CHECK (reserved_qty >= 0 AND reserved_qty <= quantity),
    UNIQUE (order_id, product_id)
);

CREATE TABLE shipping_tasks (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    assigned_to BIGINT REFERENCES users(id),
    status shipping_task_status NOT NULL DEFAULT 'PENDING',
    priority SMALLINT NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    due_date DATE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    table_name TEXT NOT NULL,
    record_id BIGINT,
    action VARCHAR(10) NOT NULL,
    changed_by BIGINT REFERENCES users(id),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_priority ON orders(priority);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_warehouse_stocks_product_id ON warehouse_stocks(product_id);
CREATE INDEX idx_shipping_tasks_status_priority ON shipping_tasks(status, priority);
CREATE INDEX idx_audit_logs_table_record ON audit_logs(table_name, record_id);

CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION audit_row_changes()
RETURNS TRIGGER AS $$
DECLARE
    changed_by_value BIGINT;
BEGIN
    changed_by_value := NULLIF(current_setting('app.user_id', true), '')::BIGINT;

    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_logs (table_name, record_id, action, changed_by, details)
        VALUES (TG_TABLE_NAME, NEW.id, TG_OP, changed_by_value, jsonb_build_object('new', to_jsonb(NEW)));
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_logs (table_name, record_id, action, changed_by, details)
        VALUES (
            TG_TABLE_NAME,
            NEW.id,
            TG_OP,
            changed_by_value,
            jsonb_build_object('old', to_jsonb(OLD), 'new', to_jsonb(NEW))
        );
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_logs (table_name, record_id, action, changed_by, details)
        VALUES (TG_TABLE_NAME, OLD.id, TG_OP, changed_by_value, jsonb_build_object('old', to_jsonb(OLD)));
        RETURN OLD;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER trg_products_updated_at
BEFORE UPDATE ON products
FOR EACH ROW
EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER trg_warehouse_stocks_updated_at
BEFORE UPDATE ON warehouse_stocks
FOR EACH ROW
EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER trg_orders_updated_at
BEFORE UPDATE ON orders
FOR EACH ROW
EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER trg_shipping_tasks_updated_at
BEFORE UPDATE ON shipping_tasks
FOR EACH ROW
EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER trg_users_audit
AFTER INSERT OR UPDATE OR DELETE ON users
FOR EACH ROW
EXECUTE FUNCTION audit_row_changes();

CREATE TRIGGER trg_products_audit
AFTER INSERT OR UPDATE OR DELETE ON products
FOR EACH ROW
EXECUTE FUNCTION audit_row_changes();

CREATE TRIGGER trg_warehouse_stocks_audit
AFTER INSERT OR UPDATE OR DELETE ON warehouse_stocks
FOR EACH ROW
EXECUTE FUNCTION audit_row_changes();

CREATE TRIGGER trg_orders_audit
AFTER INSERT OR UPDATE OR DELETE ON orders
FOR EACH ROW
EXECUTE FUNCTION audit_row_changes();

CREATE TRIGGER trg_order_items_audit
AFTER INSERT OR UPDATE OR DELETE ON order_items
FOR EACH ROW
EXECUTE FUNCTION audit_row_changes();

CREATE TRIGGER trg_shipping_tasks_audit
AFTER INSERT OR UPDATE OR DELETE ON shipping_tasks
FOR EACH ROW
EXECUTE FUNCTION audit_row_changes();

CREATE OR REPLACE VIEW v_inventory_status AS
SELECT
    p.id AS product_id,
    p.sku,
    p.name,
    p.technical_specs,
    p.unit_price,
    ws.on_hand_qty,
    ws.reserved_qty,
    ws.on_hand_qty - ws.reserved_qty AS available_qty
FROM products p
INNER JOIN warehouse_stocks ws ON ws.product_id = p.id;

COMMIT;

