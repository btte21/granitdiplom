-- Sample pgAdmin 4 scripts for daily AIS operations.

-- 1. Review current inventory availability.
SELECT * FROM v_inventory_status ORDER BY available_qty ASC, sku ASC;

-- 2. Review order and shipping workload.
SELECT
    o.order_number,
    o.customer_name,
    o.status,
    o.priority,
    st.status AS shipping_status,
    st.assigned_to
FROM orders o
LEFT JOIN shipping_tasks st ON st.order_id = o.id
ORDER BY o.created_at DESC;

-- 3. Inspect the audit trail for a specific order.
SELECT *
FROM audit_logs
WHERE table_name IN ('orders', 'order_items', 'shipping_tasks')
  AND record_id = 1
ORDER BY created_at DESC;

-- 4. Manually set the audit actor in a pgAdmin transaction before data fixes.
BEGIN;
SELECT set_config('app.user_id', '1', TRUE);
-- Example controlled update:
-- UPDATE warehouse_stocks SET on_hand_qty = on_hand_qty + 5 WHERE product_id = 1;
COMMIT;
