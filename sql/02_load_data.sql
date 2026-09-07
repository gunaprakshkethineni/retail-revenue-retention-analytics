-- =====================================================================================
-- 02_load_data.sql
-- Loads the 7 CSV files into the 7 tables.
-- =====================================================================================
--
-- HOW TO RUN (PostgreSQL, from the psql prompt):
--   \i sql/01_schema.sql
--   \i sql/02_load_data.sql
--
-- IMPORTANT: \copy is a psql client command, so it reads the file from YOUR machine
-- using a path relative to wherever you started psql. Start psql from the project
-- root folder and these paths work as-is.
--
-- (I originally used the server-side COPY command and kept getting
--  "could not open file ... Permission denied" because the Postgres service account
--  cannot see my Windows user folder. \copy fixed it.)
--
-- Load order matters: dimensions first, then fact_orders, then fact_order_items,
-- otherwise the foreign keys reject the rows.
-- =====================================================================================

\copy dim_date        FROM 'data/dim_date.csv'         WITH (FORMAT csv, HEADER true);
\copy dim_customers   FROM 'data/dim_customers.csv'    WITH (FORMAT csv, HEADER true);
\copy dim_categories  FROM 'data/dim_categories.csv'   WITH (FORMAT csv, HEADER true);
\copy dim_products    FROM 'data/dim_products.csv'     WITH (FORMAT csv, HEADER true);
\copy dim_stores      FROM 'data/dim_stores.csv'       WITH (FORMAT csv, HEADER true);
\copy fact_orders     FROM 'data/fact_orders.csv'      WITH (FORMAT csv, HEADER true);
\copy fact_order_items FROM 'data/fact_order_items.csv' WITH (FORMAT csv, HEADER true);


-- Row counts - quick check that everything actually landed.
SELECT 'dim_date'         AS table_name, COUNT(*) AS rows FROM dim_date
UNION ALL SELECT 'dim_customers',    COUNT(*) FROM dim_customers
UNION ALL SELECT 'dim_categories',   COUNT(*) FROM dim_categories
UNION ALL SELECT 'dim_products',     COUNT(*) FROM dim_products
UNION ALL SELECT 'dim_stores',       COUNT(*) FROM dim_stores
UNION ALL SELECT 'fact_orders',      COUNT(*) FROM fact_orders
UNION ALL SELECT 'fact_order_items', COUNT(*) FROM fact_order_items
ORDER BY table_name;

-- Expected row counts:
--
--                      synthetic (data/)   real (data_real/)
--   dim_categories                    8                  11
--   dim_customers                13,000                 508
--   dim_date                        731                 730
--   dim_products                    321               3,383
--   dim_stores                        6                  39
--   fact_orders                  25,635               3,280
--   fact_order_items             62,463              62,316   <- the analysis grain
--
-- Either way fact_order_items is the "60,000+ transactions" figure.


-- =====================================================================================
-- MySQL version of the load (if you are not on PostgreSQL)
-- =====================================================================================
-- LOAD DATA LOCAL INFILE 'data/dim_customers.csv'
--   INTO TABLE dim_customers
--   FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
--   LINES TERMINATED BY '\n'
--   IGNORE 1 ROWS;
-- ... repeat per table, same order as above.
--
-- SQL Server version:
-- BULK INSERT dim_customers
--   FROM 'C:\full\path\to\data\dim_customers.csv'
--   WITH (FIRSTROW = 2, FIELDTERMINATOR = ',', ROWTERMINATOR = '0x0a', FORMAT = 'CSV');
