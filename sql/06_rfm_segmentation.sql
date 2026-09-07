-- =====================================================================================
-- 06_rfm_segmentation.sql
-- RFM segmentation - turning 13,000 customers into a handful of groups marketing
-- can actually do something with.
-- =====================================================================================
--
-- RFM = Recency, Frequency, Monetary.
--   Recency   : how many days since their last order   (lower is better)
--   Frequency : how many orders they have placed        (higher is better)
--   Monetary  : how much revenue they have generated    (higher is better)
--
-- Each customer gets a 1-5 score on each dimension using NTILE(5), which splits the
-- customer base into five equal-sized buckets. I tried hard-coded thresholds first
-- ("frequency above 5 is a 5") and hated it - I would have to re-pick every number the
-- moment the data changed. NTILE just ranks everyone and cuts the list into fifths.
--
-- Recency is scored in reverse (6 - NTILE) because a LOW recency is a GOOD thing.
-- I got this backwards on my first attempt and ended up labelling my best customers
-- "Lost", which is how I found the bug.
--
-- DIALECT NOTE: date subtraction is written differently per database.
--   PostgreSQL : (ref.max_date - last_order_date)
--   SQLite     : (julianday(ref.max_date) - julianday(last_order_date))
--   MySQL      : DATEDIFF(ref.max_date, last_order_date)
--   SQL Server : DATEDIFF(day, last_order_date, ref.max_date)
-- Everything else in this file is portable.
-- =====================================================================================


-- -------------------------------------------------------------------------------------
-- Q1. Per-customer RFM scores and segment label
-- -------------------------------------------------------------------------------------
WITH ref AS (
    -- "today" for this dataset = the last day any order was placed.
    -- Hard-coding CURRENT_DATE would make every score wrong, because the data
    -- stops at 2024-12-31.
    SELECT MAX(order_date) AS max_date FROM fact_orders WHERE order_status = 'Completed'
),
customer_base AS (
    SELECT
        o.customer_id,
        MAX(o.order_date)           AS last_order_date,
        MIN(o.order_date)           AS first_order_date,
        COUNT(DISTINCT o.order_id)  AS frequency,
        SUM(oi.line_revenue)        AS monetary,
        SUM(oi.line_profit)         AS profit
    FROM   fact_orders o
    JOIN   fact_order_items oi ON oi.order_id = o.order_id
    WHERE  o.order_status = 'Completed'
    GROUP  BY o.customer_id
),
rfm_raw AS (
    SELECT
        cb.*,
        (SELECT max_date FROM ref) - cb.last_order_date AS recency_days
    FROM   customer_base cb
),
rfm_scored AS (
    SELECT
        r.*,
        6 - NTILE(5) OVER (ORDER BY recency_days ASC)  AS r_score,  -- reversed: recent = 5
        NTILE(5) OVER (ORDER BY frequency ASC)         AS f_score,
        NTILE(5) OVER (ORDER BY monetary  ASC)         AS m_score
    FROM   rfm_raw r
)
SELECT
    s.customer_id,
    c.first_name || ' ' || c.last_name        AS customer_name,
    c.country,
    c.acquisition_channel,
    s.recency_days,
    s.frequency,
    ROUND(s.monetary, 2)                      AS monetary,
    ROUND(s.profit, 2)                        AS profit,
    s.r_score,
    s.f_score,
    s.m_score,
    s.r_score + s.f_score + s.m_score         AS rfm_total,
    CASE
        WHEN s.r_score >= 4 AND s.f_score >= 4 AND s.m_score >= 4 THEN 'Champions'
        WHEN s.r_score >= 3 AND s.f_score >= 3                    THEN 'Loyal Customers'
        WHEN s.r_score >= 4 AND s.f_score <= 2                    THEN 'New Customers'
        WHEN s.r_score = 3  AND s.f_score <= 2                    THEN 'Promising'
        WHEN s.r_score <= 2 AND s.f_score >= 4 AND s.m_score >= 4 THEN 'At Risk - High Value'
        WHEN s.r_score <= 2 AND s.f_score >= 3                    THEN 'At Risk'
        WHEN s.r_score <= 2 AND s.f_score <= 2 AND s.m_score >= 3 THEN 'Hibernating'
        ELSE                                                           'Lost'
    END                                       AS rfm_segment
FROM   rfm_scored s
JOIN   dim_customers c ON c.customer_id = s.customer_id
ORDER  BY s.monetary DESC;


-- -------------------------------------------------------------------------------------
-- Q2. Segment summary - the table that goes on the Customer page of the dashboard.
--     Same logic as above, wrapped so I can aggregate it.
-- -------------------------------------------------------------------------------------
WITH ref AS (
    SELECT MAX(order_date) AS max_date FROM fact_orders WHERE order_status = 'Completed'
),
customer_base AS (
    SELECT
        o.customer_id,
        MAX(o.order_date)          AS last_order_date,
        COUNT(DISTINCT o.order_id) AS frequency,
        SUM(oi.line_revenue)       AS monetary
    FROM   fact_orders o
    JOIN   fact_order_items oi ON oi.order_id = o.order_id
    WHERE  o.order_status = 'Completed'
    GROUP  BY o.customer_id
),
rfm_scored AS (
    SELECT
        cb.customer_id,
        cb.frequency,
        cb.monetary,
        (SELECT max_date FROM ref) - cb.last_order_date        AS recency_days,
        6 - NTILE(5) OVER (ORDER BY (SELECT max_date FROM ref) - cb.last_order_date ASC) AS r_score,
        NTILE(5) OVER (ORDER BY cb.frequency ASC)              AS f_score,
        NTILE(5) OVER (ORDER BY cb.monetary  ASC)              AS m_score
    FROM   customer_base cb
),
labelled AS (
    SELECT
        s.*,
        CASE
            WHEN s.r_score >= 4 AND s.f_score >= 4 AND s.m_score >= 4 THEN 'Champions'
            WHEN s.r_score >= 3 AND s.f_score >= 3                    THEN 'Loyal Customers'
            WHEN s.r_score >= 4 AND s.f_score <= 2                    THEN 'New Customers'
            WHEN s.r_score = 3  AND s.f_score <= 2                    THEN 'Promising'
            WHEN s.r_score <= 2 AND s.f_score >= 4 AND s.m_score >= 4 THEN 'At Risk - High Value'
            WHEN s.r_score <= 2 AND s.f_score >= 3                    THEN 'At Risk'
            WHEN s.r_score <= 2 AND s.f_score <= 2 AND s.m_score >= 3 THEN 'Hibernating'
            ELSE                                                           'Lost'
        END AS rfm_segment
    FROM rfm_scored s
)
SELECT
    rfm_segment,
    COUNT(*)                                                   AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)         AS pct_of_customers,
    ROUND(SUM(monetary), 2)                                    AS revenue,
    ROUND(100.0 * SUM(monetary) / SUM(SUM(monetary)) OVER (), 1) AS pct_of_revenue,
    ROUND(AVG(monetary), 2)                                    AS avg_revenue,
    ROUND(AVG(frequency), 2)                                   AS avg_orders,
    ROUND(AVG(recency_days), 0)                                AS avg_days_since_last_order
FROM   labelled
GROUP  BY rfm_segment
ORDER  BY revenue DESC;


-- -------------------------------------------------------------------------------------
-- Q3. The action list: high-value customers who have gone quiet.
--     This is the export marketing actually asked for - a win-back mailing list.
-- -------------------------------------------------------------------------------------
WITH ref AS (
    SELECT MAX(order_date) AS max_date FROM fact_orders WHERE order_status = 'Completed'
),
customer_base AS (
    SELECT
        o.customer_id,
        MAX(o.order_date)          AS last_order_date,
        COUNT(DISTINCT o.order_id) AS frequency,
        SUM(oi.line_revenue)       AS monetary
    FROM   fact_orders o
    JOIN   fact_order_items oi ON oi.order_id = o.order_id
    WHERE  o.order_status = 'Completed'
    GROUP  BY o.customer_id
)
SELECT
    c.customer_id,
    c.first_name || ' ' || c.last_name  AS customer_name,
    c.email,
    c.country,
    c.acquisition_channel,
    cb.frequency                        AS lifetime_orders,
    ROUND(cb.monetary, 2)               AS lifetime_revenue,
    cb.last_order_date,
    (SELECT max_date FROM ref) - cb.last_order_date AS days_since_last_order
FROM   customer_base cb
JOIN   dim_customers c ON c.customer_id = cb.customer_id
WHERE  cb.frequency >= 3                                        -- proven repeat buyers
  AND  cb.monetary  >= 3000                                     -- worth spending on
  AND  (SELECT max_date FROM ref) - cb.last_order_date >= 180    -- silent for 6+ months
ORDER  BY cb.monetary DESC;
