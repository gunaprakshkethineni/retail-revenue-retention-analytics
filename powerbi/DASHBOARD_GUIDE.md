# Power BI build guide

Step-by-step instructions to rebuild the report from scratch. I wrote this partly so I
could rebuild it myself after I corrupted my `.pbix` file, and partly because a `.pbix`
is a binary blob that nobody can review on GitHub — this file is the part of the report
that is actually readable.

Everything here works with **Power BI Desktop** (free).

---

## 1. Load the data

**Option A — from CSV (fastest, no database needed)**

Home → Get data → Text/CSV, and load all seven files from `data/` (synthetic) or
`data_real/` (cleaned UCI data):

```
dim_date.csv  dim_customers.csv  dim_categories.csv  dim_products.csv
dim_stores.csv  fact_orders.csv  fact_order_items.csv
```

**Option B — from PostgreSQL** (after running `sql/01_schema.sql` and `sql/02_load_data.sql`)

Home → Get data → PostgreSQL database → server `localhost`, database `retail_analytics`.
Pick **Import**, not DirectQuery — the dataset is small and Import makes every visual
instant.

### Check the column types before you go any further

Power BI usually gets these right from CSV, but check in Power Query:

| Column | Type |
|---|---|
| `dim_date[full_date]`, `fact_orders[order_date]` | Date |
| all `line_*`, `unit_*`, `gross_amount`, `discount_amount` | Decimal number |
| `quantity`, `n_items`, `is_weekend`, `is_loyalty_member` | Whole number |
| every `*_id` | Whole number |

If `line_revenue` comes in as text, every measure returns blank and it is genuinely
confusing to debug. Fix it here, not later.

---

## 2. Build the model

Model view → drag these relationships. All are **one-to-many, single direction**,
from the dimension to the fact:

| From (one) | To (many) | Notes |
|---|---|---|
| `dim_date[full_date]` | `fact_orders[order_date]` | the active date relationship |
| `dim_customers[customer_id]` | `fact_orders[customer_id]` | |
| `dim_stores[store_id]` | `fact_orders[store_id]` | |
| `fact_orders[order_id]` | `fact_order_items[order_id]` | the fact-to-fact link |
| `dim_products[product_id]` | `fact_order_items[product_id]` | |
| `dim_categories[category_id]` | `dim_products[category_id]` | snowflaked |
| `dim_date[full_date]` | `dim_customers[First Order Date]` | **set this one to inactive** |

That last one is inactive on purpose. It only gets switched on inside the
`New Customers` measure via `USERELATIONSHIP`, so that "new customers this month"
filters by acquisition date while every other visual keeps filtering by order date.
Two active date relationships would make Power BI refuse the model anyway.

### Mark the date table

Select `dim_date` → Table tools → **Mark as date table** → `full_date`.

Skip this and `TOTALYTD`, `SAMEPERIODLASTYEAR` and `DATEADD` all return wrong
results silently, which is the worst kind of wrong.

### Hide the noise

Right-click → Hide in report view for every raw key (`customer_id`, `order_id`,
`product_id`, `store_id`, `category_id`, `date_key`) and for the helper columns
`Recency Days`, `R Score`, `F Score`, `M Score`. Anyone using the report should see
`RFM Segment`, not the three numbers behind it.

---

## 3. Add the measures

Home → Enter data → create an empty table called `_Measures` → Load.

Then paste in each measure from [`measures.dax`](measures.dax). Do them in the order
that file lists, because the later ones reference the earlier ones.

The **calculated columns** are different — those go on the tables named in the comments
(`First Order Date`, `Cohort Month`, `Lifetime Orders`, `Recency Days`, `Monetary`,
`R/F/M Score`, `RFM Segment` on `dim_customers`; `Month Index` on `fact_orders`).
Use New Column, not New Measure.

---

## 4. Page 1 — Executive Overview

The question this page answers: *how did the business do, and is it getting better or
worse?*

**KPI cards across the top** (Card visual, 5 across):

| Card | Measure | Format |
|---|---|---|
| Total Revenue | `[Total Revenue]` | Currency EUR, 2 dp, display units Millions |
| Total Profit | `[Total Profit]` | Currency EUR, Millions |
| Profit Margin | `[Profit Margin %]` | Percentage, 1 dp |
| Transactions | `[Total Transactions]` | Whole number, thousands separator |
| Active Customers | `[Active Customers]` | Whole number |

**Revenue trend** — Line and clustered column chart
X axis `dim_date[year_month]` · Column `[Total Revenue]` · Line `[Profit Margin %]`
Put the margin line on a secondary axis. The point of this visual is that revenue and
margin do *not* move together — the big promotional months have the worst margin.

**Revenue by category** — Bar chart
Y `dim_categories[category_name]` · X `[Total Revenue]` · Tooltip `[Profit Margin %]`

**Revenue by market** — Map or bar chart
Location `dim_stores[country]` · Size `[Total Revenue]`

**Slicers down the left**: `dim_date[year]`, `dim_date[quarter]`,
`dim_categories[department]`, `dim_stores[channel]`.

Format all four as dropdowns so they do not eat half the canvas.

---

## 5. Page 2 — Revenue & Profitability

The question: *where is the money actually made, and where does it leak away?*

**Cards**: `[Gross at List Price]`, `[Discount Given]`, `[Discount Rate %]`,
`[Leaked Revenue]`, `[Leakage Rate %]`.

**Category profitability** — Table or matrix
Rows `dim_categories[category_name]`
Values `[Total Revenue]`, `[Total Profit]`, `[Profit Margin %]`,
`[Discount Rate %]`, `[Margin vs Target (pts)]`

Add conditional formatting to `[Margin vs Target (pts)]` — red below zero, green above.
This is the visual that shows which categories are quietly missing their margin target.

**Top 20 products by profit** — Bar chart
Y `dim_products[product_name]` · X `[Total Profit]`
Filter: Top N = 20 by `[Total Profit]`

Worth putting a second copy next to it ranked by `[Total Revenue]`. The two lists are
not the same, and that difference is the most interesting thing on the page.

**Discount effectiveness** — Column chart
X: a `discount_band` column you can add in Power Query on `fact_order_items`
(`0%`, `1-10%`, `11-20%`, `21-30%`)
Y `[Total Revenue]` · Line `[Profit Margin %]`

**Leakage over time** — Area chart
X `dim_date[year_month]` · Y `[Leaked Revenue]`

---

## 6. Page 3 — Customer Value (the Pareto page)

The question: *which customers actually matter?*

**Page title** — Card visual bound to `[Pareto Page Title]`, so the headline number
updates itself when someone filters the page.

**The Pareto curve** — Line and clustered column chart
X axis `dim_customers[customer_id]`, sorted by `[Total Revenue]` descending
Column `[Total Revenue]` · Line `[Cumulative Revenue %]` on a secondary axis fixed 0–1

Then add a constant line at 30% on the X axis and at 60% on the Y axis
(Analytics pane → Constant line). Where those two lines cross the curve *is* the
finding, and it saves you explaining it.

> With 500+ customers on the X axis this visual gets slow and unreadable. Either
> filter to Top N = 200, or bin customers into percentiles in Power Query and plot
> the percentile instead. I did the second.

**Decile table** — Matrix
Rows: a `revenue_decile` column · Values `[Total Revenue]`, `[Cumulative Revenue %]`,
`[Revenue per Customer]`, `[Repeat Rate %]`

**Top 30% vs Bottom 70%** — Clustered bar
Axis `[Is Top 30% Customer]` · Values `[Active Customers]`, `[Revenue per Customer]`,
`[Repeat Rate %]`

**RFM segment breakdown** — Scatter or matrix
Rows `dim_customers[RFM Segment]`
Values `[Active Customers]`, `[Total Revenue]`, `[Revenue per Customer]`,
`[Avg Order Value]`

**Win-back list** — Table
`customer_id`, `email`, `country`, `[Lifetime Orders]`, `[Monetary]`, `[Recency Days]`
Filter to `RFM Segment` = "At Risk - High Value". Turn on the data export button so
marketing can actually take the list away.

---

## 7. Page 4 — Retention & Cohorts

The question: *do customers come back, and which ones stop?*

**Cards**: `[Repeat Rate %]`, `[One-Time Customers]`, `[Repeat Customers]`,
`[New Customers]`.

**The cohort retention heat map** — Matrix
Rows `dim_customers[Cohort Month]` · Columns `fact_orders[Month Index]`
Values `[Retention %]`

Format the values as Percentage 0 dp, then Conditional formatting → Background colour →
Format by Rules or a colour scale. Set the colour scale minimum to 0% and maximum to
about 30% rather than 100%, otherwise month 0 (always 100%) washes out every other
cell and the map looks empty.

**Average retention curve** — Line chart
X `fact_orders[Month Index]` · Y `[Retention %]`
This is the single most quotable visual in the whole report.

**Order frequency distribution** — Column chart
X: an `order_frequency_band` column · Y `[Active Customers]`

**One-time vs repeat value** — Clustered column
Axis: one-time / repeat · Values `[Active Customers]`, `[Total Revenue]`
The gap between the two bars is the entire argument for spending money on retention.

---

## 8. Formatting pass

Small things, but they are the difference between "a student project" and "a report":

- One theme across all pages (View → Themes). Pick one accent colour and one grey.
- Currency measures: EUR, 0 or 2 decimals, **never** the default 8.
- Percentages: 1 decimal place.
- Turn off the visual header tooltips and the data labels you do not need.
- Give every visual a title that states a fact, not a field name —
  "Revenue is growing but margin is not" beats "Sum of line_revenue by year_month".
- Sync the slicers across pages: View → Sync slicers.
- Set a consistent page size (16:9, 1280×720) so pages do not jump when you flick
  between them.
- Add a small text box on page 1 saying where the data came from and, if you used the
  real dataset, that the margin is modelled. Do not make people go digging for that.

---

## 9. Known gotchas

Things that cost me time:

1. **Margin shows as 2000%** — `[Profit Margin %]` is formatted as a percentage but the
   measure already multiplies by 100 somewhere. Pick one or the other, not both.
2. **Retention matrix is all 100%** — the `Month Index` calculated column is on the
   wrong table, or `First Order Date` is blank because it was computed without the
   `order_status = "Completed"` filter.
3. **`New Customers` equals `Active Customers`** — the inactive relationship between
   `dim_date` and `dim_customers[First Order Date]` was never created, so
   `USERELATIONSHIP` has nothing to activate.
4. **Pareto line is flat at 100%** — `ALLSELECTED` got written as `ALL`, so the ranking
   ignores the visual's own filter context.
5. **Totals do not match the SQL** — almost always the `order_status = "Completed"`
   filter missing from one measure. Run `python/verify_sql.py` and compare against
   query 1 of `sql/04_revenue_analysis.sql`; that query is the source of truth.
