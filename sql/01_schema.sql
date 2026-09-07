-- =====================================================================================
-- 01_schema.sql
-- Retail Revenue & Retention Analytics - star schema (7 tables)
-- Tested on PostgreSQL 16. See README for the small changes needed on MySQL / SQL Server.
-- =====================================================================================
--
-- I went with a star schema because the whole point of this project is a Power BI
-- dashboard, and Power BI's engine (VertiPaq) is much faster with a few dimension
-- tables hanging off a fact table than with one giant flat table.
--
--   5 dimensions:  dim_date, dim_customers, dim_categories, dim_products, dim_stores
--   2 facts     :  fact_orders (one row per order) and fact_order_items (one row per
--                  product line inside an order)
--
-- fact_order_items is the grain I actually analyse - 62,463 rows = the "60,000+
-- transactions" figure. fact_orders sits above it so that order-level things
-- (payment method, store, status, shipping) are not repeated on every line.
-- =====================================================================================

DROP TABLE IF EXISTS fact_order_items;
DROP TABLE IF EXISTS fact_orders;
DROP TABLE IF EXISTS dim_products;
DROP TABLE IF EXISTS dim_categories;
DROP TABLE IF EXISTS dim_customers;
DROP TABLE IF EXISTS dim_stores;
DROP TABLE IF EXISTS dim_date;


-- -------------------------------------------------------------------------------------
-- 1. dim_date
-- A proper date table. Power BI needs one of these to make time intelligence
-- (YTD, previous month, running totals) work reliably.
-- -------------------------------------------------------------------------------------
CREATE TABLE dim_date (
    date_key        INTEGER      PRIMARY KEY,   -- 20230115 style, easy to join on
    full_date       DATE         NOT NULL,
    year            SMALLINT     NOT NULL,
    quarter         CHAR(2)      NOT NULL,
    month_number    SMALLINT     NOT NULL,
    month_name      VARCHAR(12)  NOT NULL,
    year_month      CHAR(7)      NOT NULL,      -- '2023-01', handy for cohort analysis
    week_of_year    SMALLINT     NOT NULL,
    day_of_month    SMALLINT     NOT NULL,
    day_name        VARCHAR(10)  NOT NULL,
    is_weekend      SMALLINT     NOT NULL
);


-- -------------------------------------------------------------------------------------
-- 2. dim_customers
-- signup_date is the important one - the cohort analysis is built on it.
-- -------------------------------------------------------------------------------------
CREATE TABLE dim_customers (
    customer_id         INTEGER      PRIMARY KEY,
    first_name          VARCHAR(50)  NOT NULL,
    last_name           VARCHAR(50)  NOT NULL,
    email               VARCHAR(120) NOT NULL,
    gender              CHAR(1),
    birth_date          DATE,
    age_band            VARCHAR(10),
    city                VARCHAR(60),
    country             VARCHAR(60),
    signup_date         DATE         NOT NULL,
    acquisition_channel VARCHAR(40),
    is_loyalty_member   SMALLINT     NOT NULL DEFAULT 0
);


-- -------------------------------------------------------------------------------------
-- 3. dim_categories
-- Kept separate from dim_products (snowflaked) so I can report at department level
-- without repeating the department name on all 321 products.
-- -------------------------------------------------------------------------------------
CREATE TABLE dim_categories (
    category_id       INTEGER     PRIMARY KEY,
    category_name     VARCHAR(60) NOT NULL,
    department        VARCHAR(40) NOT NULL,
    target_margin_pct NUMERIC(5,2)             -- what the buying team is aiming for
);


-- -------------------------------------------------------------------------------------
-- 4. dim_products
-- unit_cost lives here, which is what makes the profit / margin analysis possible.
-- -------------------------------------------------------------------------------------
CREATE TABLE dim_products (
    product_id   INTEGER       PRIMARY KEY,
    product_name VARCHAR(120)  NOT NULL,
    category_id  INTEGER       NOT NULL REFERENCES dim_categories (category_id),
    brand        VARCHAR(60),
    unit_price   NUMERIC(10,2) NOT NULL CHECK (unit_price > 0),
    unit_cost    NUMERIC(10,2) NOT NULL CHECK (unit_cost  >= 0),
    launch_date  DATE
);


-- -------------------------------------------------------------------------------------
-- 5. dim_stores
-- -------------------------------------------------------------------------------------
CREATE TABLE dim_stores (
    store_id    INTEGER     PRIMARY KEY,
    store_name  VARCHAR(80) NOT NULL,
    channel     VARCHAR(20) NOT NULL,    -- Online / In-Store
    city        VARCHAR(60),
    country     VARCHAR(60),
    region      VARCHAR(40),
    opened_date DATE
);


-- -------------------------------------------------------------------------------------
-- 6. fact_orders  (order header - one row per order)
-- order_status is the revenue-leakage column: Completed / Returned / Cancelled.
-- Only 'Completed' counts towards the EUR 2.4M headline revenue.
-- -------------------------------------------------------------------------------------
CREATE TABLE fact_orders (
    order_id       INTEGER       PRIMARY KEY,
    customer_id    INTEGER       NOT NULL REFERENCES dim_customers (customer_id),
    store_id       INTEGER       NOT NULL REFERENCES dim_stores (store_id),
    order_date     DATE          NOT NULL,
    order_status   VARCHAR(15)   NOT NULL
                   CHECK (order_status IN ('Completed', 'Returned', 'Cancelled')),
    payment_method VARCHAR(30),
    shipping_cost  NUMERIC(8,2)  NOT NULL DEFAULT 0,
    n_items        SMALLINT      NOT NULL
);


-- -------------------------------------------------------------------------------------
-- 7. fact_order_items  (order line - the analysis grain, 62,463 rows)
-- I store the derived amounts (line_revenue / line_cost / line_profit) rather than
-- recomputing them every time. In a real warehouse this is a normal trade-off:
-- a bit of redundancy in exchange for much simpler and faster queries downstream.
-- -------------------------------------------------------------------------------------
CREATE TABLE fact_order_items (
    order_item_id   INTEGER       PRIMARY KEY,
    order_id        INTEGER       NOT NULL REFERENCES fact_orders (order_id),
    product_id      INTEGER       NOT NULL REFERENCES dim_products (product_id),
    quantity        SMALLINT      NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(10,2) NOT NULL,   -- price at the time of sale
    unit_cost       NUMERIC(10,2) NOT NULL,   -- cost  at the time of sale
    discount_pct    NUMERIC(4,2)  NOT NULL DEFAULT 0,
    gross_amount    NUMERIC(12,2) NOT NULL,   -- unit_price * quantity
    discount_amount NUMERIC(12,2) NOT NULL,   -- how much was given away
    line_revenue    NUMERIC(12,2) NOT NULL,   -- gross_amount - discount_amount
    line_cost       NUMERIC(12,2) NOT NULL,   -- unit_cost * quantity
    line_profit     NUMERIC(12,2) NOT NULL    -- line_revenue - line_cost
);


-- -------------------------------------------------------------------------------------
-- Indexes
-- Without these the cohort query below took ~4 seconds on my laptop; with them it
-- is well under a second.
-- -------------------------------------------------------------------------------------
CREATE INDEX idx_orders_customer  ON fact_orders (customer_id);
CREATE INDEX idx_orders_date      ON fact_orders (order_date);
CREATE INDEX idx_orders_status    ON fact_orders (order_status);
CREATE INDEX idx_orders_store     ON fact_orders (store_id);
CREATE INDEX idx_items_order      ON fact_order_items (order_id);
CREATE INDEX idx_items_product    ON fact_order_items (product_id);
CREATE INDEX idx_customers_signup ON dim_customers (signup_date);
