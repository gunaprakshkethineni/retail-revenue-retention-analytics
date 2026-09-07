-- =====================================================================================
-- 07_pareto_top_customers.sql
-- The headline finding: the top 30% of customers generate ~60% of total revenue.
-- =====================================================================================
--
-- Method: rank every paying customer by lifetime revenue, work out each one's
-- cumulative share of the total, then read off the share at the 30% mark.
--
-- The whole thing rests on one window function pattern:
--   SUM(revenue) OVER (ORDER BY revenue DESC ROWS UNBOUNDED PRECEDING)
-- which gives a running total down the ranked list. This is the bit of SQL I had to
-- read about most - I understood GROUP BY fine, but a running total that keeps every
-- row instead of collapsing them took me a while to get my head around.
--
-- I went into this expecting the 80/20 rule and wrote "top 30% = 60%" into my project
-- plan before I had run anything. The real answer came back far more extreme, and my
-- first instinct was that I had written the query wrong. I had not.
-- =====================================================================================


-- -------------------------------------------------------------------------------------
-- Q1. Per-customer Pareto table (this is what Power BI loads for the Pareto chart)
-- -------------------------------------------------------------------------------------
WITH customer_revenue AS (
    SELECT
        o.customer_id,
        SUM(oi.line_revenue)       AS revenue,
        SUM(oi.line_profit)        AS profit,
        COUNT(DISTINCT o.order_id) AS orders
    FROM   fact_orders o
    JOIN   fact_order_items oi ON oi.order_id = o.order_id
    WHERE  o.order_status = 'Completed'
    GROUP  BY o.customer_id
),
ranked AS (
    SELECT
        cr.*,
        ROW_NUMBER() OVER (ORDER BY revenue DESC)                     AS revenue_rank,
        COUNT(*)     OVER ()                                          AS total_customers,
        SUM(revenue) OVER ()                                          AS total_revenue,
        SUM(revenue) OVER (ORDER BY revenue DESC, customer_id
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                                                                      AS cumulative_revenue
    FROM   customer_revenue cr
)
SELECT
    r.revenue_rank,
    r.customer_id,
    c.country,
    c.acquisition_channel,
    r.orders,
    ROUND(r.revenue, 2)                                               AS revenue,
    ROUND(r.profit, 2)                                                AS profit,
    ROUND(100.0 * r.revenue_rank / r.total_customers, 2)              AS customer_percentile,
    ROUND(100.0 * r.cumulative_revenue / r.total_revenue, 2)          AS cumulative_revenue_pct
FROM   ranked r
JOIN   dim_customers c ON c.customer_id = r.customer_id
ORDER  BY r.revenue_rank;


-- -------------------------------------------------------------------------------------
-- Q2. THE headline number: what share of revenue does the top 30% actually own?
-- -------------------------------------------------------------------------------------
WITH customer_revenue AS (
    SELECT o.customer_id, SUM(oi.line_revenue) AS revenue
    FROM   fact_orders o
    JOIN   fact_order_items oi ON oi.order_id = o.order_id
    WHERE  o.order_status = 'Completed'
    GROUP  BY o.customer_id
),
ranked AS (
    SELECT
        revenue,
        ROW_NUMBER() OVER (ORDER BY revenue DESC) AS revenue_rank,
        COUNT(*)     OVER ()                      AS total_customers,
        SUM(revenue) OVER ()                      AS total_revenue
    FROM   customer_revenue
)
SELECT
    total_customers,
    SUM(CASE WHEN revenue_rank <= total_customers * 0.30
             THEN 1 ELSE 0 END)                                       AS top_30pct_customers,
    ROUND(SUM(CASE WHEN revenue_rank <= total_customers * 0.30
                   THEN revenue ELSE 0 END), 2)                       AS top_30pct_revenue,
    ROUND(MAX(total_revenue), 2)                                      AS total_revenue,
    ROUND(100.0 * SUM(CASE WHEN revenue_rank <= total_customers * 0.30
                           THEN revenue ELSE 0 END)
          / MAX(total_revenue), 1)                                    AS top_30pct_revenue_share
FROM   ranked
GROUP  BY total_customers;


-- -------------------------------------------------------------------------------------
-- Q3. Full decile breakdown - shows the concentration curve, not just one number.
--     Decile 1 = the top 10% of customers by revenue.
-- -------------------------------------------------------------------------------------
WITH customer_revenue AS (
    SELECT
        o.customer_id,
        SUM(oi.line_revenue)       AS revenue,
        SUM(oi.line_profit)        AS profit,
        COUNT(DISTINCT o.order_id) AS orders
    FROM   fact_orders o
    JOIN   fact_order_items oi ON oi.order_id = o.order_id
    WHERE  o.order_status = 'Completed'
    GROUP  BY o.customer_id
),
deciled AS (
    SELECT *, NTILE(10) OVER (ORDER BY revenue DESC) AS revenue_decile
    FROM   customer_revenue
)
SELECT
    revenue_decile,
    COUNT(*)                                                          AS customers,
    ROUND(SUM(revenue), 2)                                            AS revenue,
    ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 1)        AS pct_of_revenue,
    ROUND(SUM(SUM(revenue)) OVER (ORDER BY revenue_decile) * 100.0
          / SUM(SUM(revenue)) OVER (), 1)                             AS cumulative_pct_of_revenue,
    ROUND(AVG(revenue), 2)                                            AS avg_revenue_per_customer,
    ROUND(AVG(orders), 2)                                             AS avg_orders,
    ROUND(100.0 * SUM(profit) / SUM(revenue), 1)                      AS margin_pct
FROM   deciled
GROUP  BY revenue_decile
ORDER  BY revenue_decile;


-- -------------------------------------------------------------------------------------
-- Q4. Who ARE the top 30%? Profiling them is what makes the finding actionable -
--     you cannot target a segment you cannot describe.
-- -------------------------------------------------------------------------------------
WITH customer_revenue AS (
    SELECT
        o.customer_id,
        SUM(oi.line_revenue)       AS revenue,
        COUNT(DISTINCT o.order_id) AS orders
    FROM   fact_orders o
    JOIN   fact_order_items oi ON oi.order_id = o.order_id
    WHERE  o.order_status = 'Completed'
    GROUP  BY o.customer_id
),
flagged AS (
    SELECT
        cr.*,
        CASE WHEN ROW_NUMBER() OVER (ORDER BY revenue DESC)
                  <= COUNT(*) OVER () * 0.30
             THEN 'Top 30%' ELSE 'Bottom 70%' END AS value_group
    FROM   customer_revenue cr
)
SELECT
    f.value_group,
    COUNT(*)                                        AS customers,
    ROUND(AVG(f.orders), 2)                         AS avg_orders,
    ROUND(AVG(f.revenue), 2)                        AS avg_lifetime_revenue,
    ROUND(100.0 * SUM(CASE WHEN c.is_loyalty_member = 1 THEN 1 ELSE 0 END)
          / COUNT(*), 1)                            AS pct_loyalty_members,
    ROUND(100.0 * SUM(CASE WHEN f.orders >= 2 THEN 1 ELSE 0 END)
          / COUNT(*), 1)                            AS pct_repeat_buyers
FROM   flagged f
JOIN   dim_customers c ON c.customer_id = f.customer_id
GROUP  BY f.value_group
ORDER  BY avg_lifetime_revenue DESC;


-- -------------------------------------------------------------------------------------
-- Q5. Which acquisition channel produces top-30% customers most often?
--     Directly answers "where should the marketing budget go".
-- -------------------------------------------------------------------------------------
WITH customer_revenue AS (
    SELECT o.customer_id, SUM(oi.line_revenue) AS revenue
    FROM   fact_orders o
    JOIN   fact_order_items oi ON oi.order_id = o.order_id
    WHERE  o.order_status = 'Completed'
    GROUP  BY o.customer_id
),
flagged AS (
    SELECT
        cr.customer_id,
        cr.revenue,
        CASE WHEN ROW_NUMBER() OVER (ORDER BY cr.revenue DESC)
                  <= COUNT(*) OVER () * 0.30 THEN 1 ELSE 0 END AS is_top30
    FROM customer_revenue cr
)
SELECT
    c.acquisition_channel,
    COUNT(*)                                                   AS customers,
    SUM(f.is_top30)                                            AS top30_customers,
    ROUND(100.0 * SUM(f.is_top30) / COUNT(*), 1)               AS pct_that_become_top30,
    ROUND(SUM(f.revenue), 2)                                   AS revenue,
    ROUND(AVG(f.revenue), 2)                                   AS avg_revenue_per_customer
FROM   flagged f
JOIN   dim_customers c ON c.customer_id = f.customer_id
GROUP  BY c.acquisition_channel
ORDER  BY pct_that_become_top30 DESC;
