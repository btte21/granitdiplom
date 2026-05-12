BEGIN;

INSERT INTO users (full_name, email, password_hash, role)
VALUES
    (
        'System Administrator',
        'admin@granit-ural.local',
        'pbkdf2_sha256$600000$adminsalt1234567890abcdef12345678$627cddce8429b0e1502759fb98c0bb3d327ab34422683ef24ae229e379ef1f3b',
        'ADMIN'
    ),
    (
        'Distribution Manager',
        'manager@granit-ural.local',
        'pbkdf2_sha256$600000$managersalt1234567890abcdef1234$dc35ff276e22503f368ee56faff65c51e5216ada9c1735b128f9f5ef1225dba1',
        'MANAGER'
    ),
    (
        'Warehouse Operator',
        'warehouse@granit-ural.local',
        'pbkdf2_sha256$600000$warehousesalt1234567890abcdef$56ac71952fb3b1bd5e6699515077b061aa35d770a4935ba5a73e8f5e2d238c3f',
        'WAREHOUSE'
    );

INSERT INTO products (sku, name, technical_specs, unit_price)
VALUES
    ('GU-SRV-001', 'Rack Server 2U', '{"cpu": "Xeon Silver", "ram": "64 GB", "storage": "2 x 1.92 TB SSD"}', 250000.00),
    ('GU-LIC-002', 'Endpoint Security Suite', '{"license_term": "12 months", "seats": 50, "support": "Business"}', 75000.00),
    ('GU-NB-003', 'Business Notebook', '{"cpu": "Core i7", "ram": "32 GB", "ssd": "1 TB", "screen": "15.6"}', 98000.00),
    ('GU-NET-004', '24-Port Managed Switch', '{"ports": 24, "uplinks": "4 x SFP+", "power": "Dual PSU"}', 115000.00),
    ('GU-UPS-005', 'Online UPS 5kVA', '{"power": "5000 VA", "runtime": "18 min", "form_factor": "Tower"}', 168000.00);

INSERT INTO warehouse_stocks (product_id, on_hand_qty, reserved_qty)
SELECT p.id, seed.on_hand_qty, seed.reserved_qty
FROM products p
INNER JOIN (
    VALUES
        ('GU-SRV-001', 10, 2),
        ('GU-LIC-002', 25, 0),
        ('GU-NB-003', 8, 1),
        ('GU-NET-004', 14, 0),
        ('GU-UPS-005', 6, 0)
) AS seed(sku, on_hand_qty, reserved_qty)
    ON seed.sku = p.sku;

COMMIT;

