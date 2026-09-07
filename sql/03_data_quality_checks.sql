-- =====================================================================================
-- 03_data_quality_checks.sql
-- Run this straight after loading. Every query here should return ZERO rows
-- (except the last one, which is a summary).
-- =====================================================================================
--
-- I added this file after I built the first version of the dashboard and the revenue
-- number looked wrong. It turned out I had loaded fact_order_items twice. Now I run
-- these checks every time before I refresh Power BI.
-- =====================================================================================


-- 1. Orphan order items - a line pointing at an order that does not exist
SELECT oi.order_item_id, oi.order_id
FROM   fact_order_items oi
LEFT   JOIN fact_orders o ON o.order_id = oi.order_id
WHERE  o.order_id IS NULL;


-- 2. Orphan orders - an order pointing at a customer that does not exist
SELECT o.order_id, o.customer_id
FROM   fact_orders o
LEFT   JOIN dim_customers c ON c.customer_id = o.customer_id
WHERE  c.customer_id IS NULL;


-- 3. Orders with no lines at all (would silently drag the average order value down)
SELECT o.order_id
FROM   fact_orders o
LEFT   JOIN fact_order_items oi ON oi.order_id = o.order_id
WHERE  oi.order_item_id IS NULL;


-- 4. Duplicate order items (this is the one that caught me out)
SELECT order_id, product_id, COUNT(*) AS times
FROM   fact_order_items
GROUP  BY order_id, product_id
HAVING COUNT(*) > 1;


-- 5. Arithmetic that does not add up - the derived columns must be consistent.
--    Allowing 1 cent of rounding tolerance.
SELECT order_item_id,
       gross_amount,
       discount_amount,
       line_revenue,
       line_cost,
       line_profit
FROM   fact_order_items
WHERE  ABS(gross_amount  - (unit_price * quantity))                > 0.01
   OR  ABS(line_revenue  - (gross_amount - discount_amount))       > 0.01
   OR  ABS(line_cost     - (unit_cost * quantity))                 > 0.01
   OR  ABS(line_profit   - (line_revenue - line_cost))             > 0.01;


-- 6. Impossible values
SELECT order_item_id, quantity, unit_price, discount_pct
FROM   fact_order_items
WHERE  quantity     <= 0
   OR  unit_price   <= 0
   OR  discount_pct <  0
   OR  discount_pct >  1;


-- 7. Products priced below cost (would show up as negative margin in the dashboard)
SELECT product_id, product_name, unit_price, unit_cost
FROM   dim_products
WHERE  unit_cost > unit_price;


-- 8. Orders dated before the customer even signed up
SELECT o.order_id, o.order_date, c.signup_date
FROM   fact_orders o
JOIN   dim_customers c ON c.customer_id = o.customer_id
WHERE  o.order_date < c.signup_date;


-- 9. Order dates that fall outside dim_date (would break Power BI time intelligence)
SELECT DISTINCT o.order_date
FROM   fact_orders o
LEFT   JOIN dim_date d ON d.full_date = o.order_date
WHERE  d.date_key IS NULL;


-- 10. Summary - this one IS meant to return rows.
SELECT
    COUNT(*)                                                   AS total_order_lines,
    COUNT(DISTINCT oi.order_id)                                AS total_orders,
    MIN(o.order_date)                                          AS first_order,
    MAX(o.order_date)                                          AS last_order,
    ROUND(SUM(CASE WHEN o.order_status = 'Completed'
                   THEN oi.line_revenue ELSE 0 END), 2)        AS completed_revenue,
    ROUND(SUM(CASE WHEN o.order_status <> 'Completed'
                   THEN oi.line_revenue ELSE 0 END), 2)        AS leaked_revenue
FROM   fact_order_items oi
JOIN   fact_orders o ON o.order_id = oi.order_id;
