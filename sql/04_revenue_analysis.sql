-- =====================================================================================
-- 04_revenue_analysis.sql
-- Where the money comes from, and where it leaks out.
-- =====================================================================================
--
-- A note on style: I join to dim_date and use its year_month column instead of calling
-- DATE_TRUNC / TO_CHAR everywhere. Two reasons - it is faster (no function call per
-- row, so the index still gets used), and it means these queries also run unchanged
-- on SQLite and MySQL, which is how I tested them before installing Postgres.
--
-- The rule I follow in every query in this file: revenue only counts when
-- order_status = 'Completed'. I learned this the annoying way - my first dashboard
-- reported EUR 2.49M and I could not work out why it would not match my SQL, and it was
-- because returns were quietly being added in. Now the filter goes in first, every time,
-- and returns get measured on their own as leakage.
-- =====================================================================================


-- -------------------------------------------------------------------------------------
-- Q1. The headline KPIs - these are the numbers on the dashboard's top row
-- -------------------------------------------------------------------------------------
SELECT
    ROUND(SUM(oi.line_revenue), 2)                                      AS total_revenue,
    ROUND(SUM(oi.line_cost), 2)                                         AS total_cost,
    ROUND(SUM(oi.line_profit), 2)                                       AS total_profit,
    ROUND(100.0 * SUM(oi.line_profit) / SUM(oi.line_revenue), 2)        AS profit_margin_pct,
    COUNT(*)                                                            AS total_transactions,
    COUNT(DISTINCT oi.order_id)                                         AS total_orders,
    COUNT(DISTINCT o.customer_id)                                       AS active_customers,
    ROUND(SUM(oi.line_revenue) / COUNT(DISTINCT oi.order_id), 2)        AS avg_order_value,
    ROUND(SUM(oi.line_revenue) / COUNT(DISTINCT o.customer_id), 2)      AS revenue_per_customer
FROM   fact_order_items oi
JOIN   fact_orders o ON o.order_id = oi.order_id
WHERE  o.order_status = 'Completed';


-- -------------------------------------------------------------------------------------
-- Q2. Monthly revenue trend, with month-over-month growth
-- -------------------------------------------------------------------------------------
WITH monthly AS (
    SELECT
        d.year_month,
        SUM(oi.line_revenue) AS revenue,
        SUM(oi.line_profit)  AS profit,
        COUNT(DISTINCT oi.order_id) AS orders
    FROM   fact_order_items oi
    JOIN   fact_orders o ON o.order_id = oi.order_id
    JOIN   dim_date    d ON d.full_date = o.order_date
    WHERE  o.order_status = 'Completed'
    GROUP  BY d.year_month
)
SELECT
    year_month,
    ROUND(revenue, 2)                                           AS revenue,
    ROUND(profit, 2)                                            AS profit,
    ROUND(100.0 * profit / revenue, 1)                          AS margin_pct,
    orders,
    ROUND(LAG(revenue) OVER (ORDER BY year_month), 2)           AS prev_month_revenue,
    ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY year_month))
          / LAG(revenue) OVER (ORDER BY year_month), 1)         AS mom_growth_pct
FROM   monthly
ORDER  BY year_month;


-- -------------------------------------------------------------------------------------
-- Q3. Category performance - this is where the margin story lives.
--     Grocery sells the most units but earns the least per euro.
-- -------------------------------------------------------------------------------------
SELECT
    c.department,
    c.category_name,
    COUNT(*)                                                     AS transactions,
    SUM(oi.quantity)                                             AS units_sold,
    ROUND(SUM(oi.line_revenue), 2)                               AS revenue,
    ROUND(SUM(oi.line_profit), 2)                                AS profit,
    ROUND(100.0 * SUM(oi.line_profit) / SUM(oi.line_revenue), 1) AS margin_pct,
    c.target_margin_pct,
    ROUND(100.0 * SUM(oi.line_revenue)
          / SUM(SUM(oi.line_revenue)) OVER (), 1)                AS pct_of_total_revenue
FROM   fact_order_items oi
JOIN   fact_orders     o ON o.order_id    = oi.order_id
JOIN   dim_products    p ON p.product_id  = oi.product_id
JOIN   dim_categories  c ON c.category_id = p.category_id
WHERE  o.order_status = 'Completed'
GROUP  BY c.department, c.category_name, c.target_margin_pct
ORDER  BY revenue DESC;


-- -------------------------------------------------------------------------------------
-- Q4. Store / channel performance
-- -------------------------------------------------------------------------------------
SELECT
    s.channel,
    s.store_name,
    s.city,
    s.country,
    COUNT(DISTINCT o.order_id)                                   AS orders,
    ROUND(SUM(oi.line_revenue), 2)                               AS revenue,
    ROUND(SUM(oi.line_profit), 2)                                AS profit,
    ROUND(100.0 * SUM(oi.line_profit) / SUM(oi.line_revenue), 1) AS margin_pct,
    ROUND(SUM(oi.line_revenue) / COUNT(DISTINCT o.order_id), 2)  AS avg_order_value
FROM   fact_order_items oi
JOIN   fact_orders o ON o.order_id = oi.order_id
JOIN   dim_stores  s ON s.store_id = o.store_id
WHERE  o.order_status = 'Completed'
GROUP  BY s.channel, s.store_name, s.city, s.country
ORDER  BY revenue DESC;


-- -------------------------------------------------------------------------------------
-- Q5. Top 20 products by PROFIT, not by revenue.
--     I ran this by revenue first, then by profit, and noticed the two lists are not the
--     same products. That surprised me enough that I put both on the dashboard side by
--     side - the best sellers are not the best earners, and that is the sort of thing a
--     buying team would actually want to know.
-- -------------------------------------------------------------------------------------
SELECT
    p.product_id,
    p.product_name,
    c.category_name,
    SUM(oi.quantity)                                             AS units_sold,
    ROUND(SUM(oi.line_revenue), 2)                               AS revenue,
    ROUND(SUM(oi.line_profit), 2)                                AS profit,
    ROUND(100.0 * SUM(oi.line_profit) / SUM(oi.line_revenue), 1) AS margin_pct
FROM   fact_order_items oi
JOIN   fact_orders    o ON o.order_id    = oi.order_id
JOIN   dim_products   p ON p.product_id  = oi.product_id
JOIN   dim_categories c ON c.category_id = p.category_id
WHERE  o.order_status = 'Completed'
GROUP  BY p.product_id, p.product_name, c.category_name
ORDER  BY profit DESC
LIMIT  20;


-- -------------------------------------------------------------------------------------
-- Q6. REVENUE LEAKAGE - the "addressed revenue leakage" part of the project.
--     Two leaks: (a) orders that get returned or cancelled, (b) discounts given away.
-- -------------------------------------------------------------------------------------

-- (a) Returns and cancellations
SELECT
    o.order_status,
    COUNT(DISTINCT o.order_id)                                   AS orders,
    COUNT(*)                                                     AS order_lines,
    ROUND(SUM(oi.line_revenue), 2)                               AS revenue_value,
    ROUND(100.0 * SUM(oi.line_revenue)
          / SUM(SUM(oi.line_revenue)) OVER (), 2)                AS pct_of_gross_demand
FROM   fact_order_items oi
JOIN   fact_orders o ON o.order_id = oi.order_id
GROUP  BY o.order_status
ORDER  BY revenue_value DESC;


-- (b) Discount leakage by category - how much list price we gave away
SELECT
    c.category_name,
    ROUND(SUM(oi.gross_amount), 2)                                  AS gross_at_list_price,
    ROUND(SUM(oi.discount_amount), 2)                               AS discount_given,
    ROUND(100.0 * SUM(oi.discount_amount) / SUM(oi.gross_amount), 1) AS discount_rate_pct,
    ROUND(SUM(oi.line_revenue), 2)                                  AS net_revenue,
    ROUND(100.0 * SUM(oi.line_profit) / SUM(oi.line_revenue), 1)    AS margin_pct
FROM   fact_order_items oi
JOIN   fact_orders    o ON o.order_id    = oi.order_id
JOIN   dim_products   p ON p.product_id  = oi.product_id
JOIN   dim_categories c ON c.category_id = p.category_id
WHERE  o.order_status = 'Completed'
GROUP  BY c.category_name
ORDER  BY discount_given DESC;


-- (c) Which discount band actually pays for itself?
--     Sanity check on whether deep discounts are buying us bigger baskets.
SELECT
    CASE
        WHEN oi.discount_pct = 0                          THEN '0% (full price)'
        WHEN oi.discount_pct <= 0.10                      THEN '1-10%'
        WHEN oi.discount_pct <= 0.20                      THEN '11-20%'
        ELSE                                                   '21-30%'
    END                                                          AS discount_band,
    COUNT(*)                                                     AS transactions,
    ROUND(SUM(oi.line_revenue), 2)                               AS revenue,
    ROUND(SUM(oi.line_profit), 2)                                AS profit,
    ROUND(100.0 * SUM(oi.line_profit) / SUM(oi.line_revenue), 1) AS margin_pct,
    ROUND(AVG(oi.quantity), 2)                                   AS avg_units_per_line
FROM   fact_order_items oi
JOIN   fact_orders o ON o.order_id = oi.order_id
WHERE  o.order_status = 'Completed'
GROUP  BY 1
ORDER  BY 1;
