-- =====================================================================================
-- 05_cohort_retention.sql
-- Cohort analysis - the "high customer drop-off" half of the project.
-- =====================================================================================
--
-- The idea: group every customer by the month of their FIRST purchase (their cohort),
-- then follow that same group month by month and count how many of them come back.
--
-- I started out just plotting active customers per month, and it looked fine - the line
-- went up. It was only when I split it by cohort that I could see retention was actually
-- poor and the growth in new customers was covering it up. That is the whole reason
-- cohort analysis exists, and I did not really get it until I saw it in my own data.
--
-- month_index = how many months after their first purchase.
--   month_index 0 = the month they joined (always 100% by definition)
--   month_index 1 = came back the very next month
--   ...
--
-- Month arithmetic trick: instead of date functions, I turn (year, month) into a
-- single number with year * 12 + month and subtract. Works on every SQL dialect.
-- =====================================================================================


-- -------------------------------------------------------------------------------------
-- Q1. The retention matrix (long format - this is the one Power BI loads)
-- -------------------------------------------------------------------------------------
WITH customer_orders AS (
    -- every completed order, tagged with the month it happened in
    SELECT
        o.customer_id,
        o.order_id,
        d.year_month                       AS order_month,
        d.year * 12 + d.month_number       AS order_month_num
    FROM   fact_orders o
    JOIN   dim_date    d ON d.full_date = o.order_date
    WHERE  o.order_status = 'Completed'
),
first_order AS (
    -- each customer's cohort = the month of their first ever completed order
    SELECT
        customer_id,
        MIN(order_month)     AS cohort_month,
        MIN(order_month_num) AS cohort_month_num
    FROM   customer_orders
    GROUP  BY customer_id
),
activity AS (
    SELECT
        f.cohort_month,
        co.customer_id,
        co.order_month_num - f.cohort_month_num AS month_index
    FROM   customer_orders co
    JOIN   first_order f ON f.customer_id = co.customer_id
),
cohort_size AS (
    SELECT cohort_month, COUNT(DISTINCT customer_id) AS cohort_customers
    FROM   first_order
    GROUP  BY cohort_month
)
SELECT
    a.cohort_month,
    cs.cohort_customers,
    a.month_index,
    COUNT(DISTINCT a.customer_id)                                        AS active_customers,
    ROUND(100.0 * COUNT(DISTINCT a.customer_id) / cs.cohort_customers, 1) AS retention_pct
FROM   activity a
JOIN   cohort_size cs ON cs.cohort_month = a.cohort_month
GROUP  BY a.cohort_month, cs.cohort_customers, a.month_index
ORDER  BY a.cohort_month, a.month_index;


-- -------------------------------------------------------------------------------------
-- Q2. The average retention curve across all cohorts.
--     This is the single chart that makes the drop-off obvious.
--     Only cohorts that have had the chance to reach that month_index are counted,
--     otherwise recent cohorts drag the later months down artificially.
-- -------------------------------------------------------------------------------------
WITH customer_orders AS (
    SELECT o.customer_id, d.year_month AS order_month,
           d.year * 12 + d.month_number AS order_month_num
    FROM   fact_orders o
    JOIN   dim_date d ON d.full_date = o.order_date
    WHERE  o.order_status = 'Completed'
),
first_order AS (
    SELECT customer_id, MIN(order_month) AS cohort_month,
           MIN(order_month_num) AS cohort_month_num
    FROM   customer_orders GROUP BY customer_id
),
max_month AS (
    SELECT MAX(order_month_num) AS last_month_num FROM customer_orders
),
activity AS (
    SELECT f.cohort_month, f.cohort_month_num, co.customer_id,
           co.order_month_num - f.cohort_month_num AS month_index
    FROM   customer_orders co
    JOIN   first_order f ON f.customer_id = co.customer_id
),
cohort_size AS (
    SELECT cohort_month, cohort_month_num, COUNT(DISTINCT customer_id) AS cohort_customers
    FROM   first_order GROUP BY cohort_month, cohort_month_num
),
-- Collapse to ONE row per (cohort, month_index) first. Without this step the join
-- back to cohort_size repeats the cohort total once per active customer, so
-- SUM(cohort_customers) explodes and every retention figure comes out near zero.
-- (I hit exactly that bug the first time I wrote this query.)
per_cohort_month AS (
    SELECT
        a.cohort_month,
        a.month_index,
        COUNT(DISTINCT a.customer_id) AS active_customers
    FROM   activity a
    JOIN   cohort_size cs ON cs.cohort_month = a.cohort_month
    CROSS  JOIN max_month m
    WHERE  cs.cohort_month_num + a.month_index <= m.last_month_num
    GROUP  BY a.cohort_month, a.month_index
)
SELECT
    p.month_index,
    SUM(cs.cohort_customers)                                           AS customers_at_risk,
    SUM(p.active_customers)                                            AS returning_customers,
    ROUND(100.0 * SUM(p.active_customers) / SUM(cs.cohort_customers), 1)
                                                                       AS avg_retention_pct
FROM   per_cohort_month p
JOIN   cohort_size cs ON cs.cohort_month = p.cohort_month
GROUP  BY p.month_index
ORDER  BY p.month_index;


-- -------------------------------------------------------------------------------------
-- Q3. How many orders does a customer actually place? (the blunt version of the story)
-- -------------------------------------------------------------------------------------
WITH per_customer AS (
    SELECT o.customer_id, COUNT(DISTINCT o.order_id) AS orders
    FROM   fact_orders o
    WHERE  o.order_status = 'Completed'
    GROUP  BY o.customer_id
)
SELECT
    CASE WHEN orders = 1 THEN '1 order (one-time buyer)'
         WHEN orders = 2 THEN '2 orders'
         WHEN orders BETWEEN 3 AND 4 THEN '3-4 orders'
         WHEN orders BETWEEN 5 AND 9 THEN '5-9 orders'
         ELSE '10+ orders' END                                        AS order_frequency_band,
    COUNT(*)                                                          AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)                AS pct_of_customers
FROM   per_customer
GROUP  BY 1
ORDER  BY MIN(orders);


-- -------------------------------------------------------------------------------------
-- Q4. Repeat rate, and what a repeat customer is worth vs a one-time buyer.
--     This is the number I used to argue that retention spend is worth it.
-- -------------------------------------------------------------------------------------
WITH per_customer AS (
    SELECT
        o.customer_id,
        COUNT(DISTINCT o.order_id) AS orders,
        SUM(oi.line_revenue)       AS revenue
    FROM   fact_orders o
    JOIN   fact_order_items oi ON oi.order_id = o.order_id
    WHERE  o.order_status = 'Completed'
    GROUP  BY o.customer_id
)
SELECT
    CASE WHEN orders = 1 THEN 'One-time buyer' ELSE 'Repeat buyer' END AS customer_type,
    COUNT(*)                                                           AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)                 AS pct_of_customers,
    ROUND(SUM(revenue), 2)                                             AS revenue,
    ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 1)         AS pct_of_revenue,
    ROUND(AVG(revenue), 2)                                             AS avg_revenue_per_customer
FROM   per_customer
GROUP  BY 1
ORDER  BY revenue DESC;


-- -------------------------------------------------------------------------------------
-- Q5. Retention by acquisition channel - which channels bring customers that stick?
--     Cheap channels that only bring one-time buyers are the real revenue leak.
-- -------------------------------------------------------------------------------------
WITH per_customer AS (
    SELECT
        o.customer_id,
        COUNT(DISTINCT o.order_id) AS orders,
        SUM(oi.line_revenue)       AS revenue
    FROM   fact_orders o
    JOIN   fact_order_items oi ON oi.order_id = o.order_id
    WHERE  o.order_status = 'Completed'
    GROUP  BY o.customer_id
)
SELECT
    c.acquisition_channel,
    COUNT(*)                                                          AS customers,
    SUM(CASE WHEN pc.orders >= 2 THEN 1 ELSE 0 END)                   AS repeat_customers,
    ROUND(100.0 * SUM(CASE WHEN pc.orders >= 2 THEN 1 ELSE 0 END)
          / COUNT(*), 1)                                              AS repeat_rate_pct,
    ROUND(AVG(pc.revenue), 2)                                         AS avg_lifetime_revenue,
    ROUND(SUM(pc.revenue), 2)                                         AS total_revenue
FROM   per_customer pc
JOIN   dim_customers c ON c.customer_id = pc.customer_id
GROUP  BY c.acquisition_channel
ORDER  BY repeat_rate_pct DESC;


-- -------------------------------------------------------------------------------------
-- Q6. Average gap between one order and the next.
--     Feeds the "win-back" trigger: if the usual gap is ~N days, a customer who has
--     been silent for 2N days is probably gone.
--
--     NOTE: this is the one query in the project that is not dialect-portable, because
--     subtracting two dates is written differently everywhere.
--       PostgreSQL : o2.order_date - o1.order_date
--       SQLite     : julianday(o2.order_date) - julianday(o1.order_date)
--       MySQL      : DATEDIFF(o2.order_date, o1.order_date)
--       SQL Server : DATEDIFF(day, o1.order_date, o2.order_date)
-- -------------------------------------------------------------------------------------
WITH ordered AS (
    SELECT
        customer_id,
        order_date,
        LAG(order_date) OVER (PARTITION BY customer_id ORDER BY order_date) AS prev_order_date
    FROM   fact_orders
    WHERE  order_status = 'Completed'
)
SELECT
    COUNT(*)                                              AS repeat_purchase_events,
    ROUND(AVG(order_date - prev_order_date), 1)           AS avg_days_between_orders,
    MIN(order_date - prev_order_date)                     AS min_days,
    MAX(order_date - prev_order_date)                     AS max_days
FROM   ordered
WHERE  prev_order_date IS NOT NULL;
