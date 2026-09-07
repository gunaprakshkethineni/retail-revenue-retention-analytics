"""
clean_online_retail.py
----------------------
Takes the REAL "Online Retail II" dataset from the UCI Machine Learning Repository
and turns it into the same 7-table star schema the rest of this project uses.

Source : https://archive.ics.uci.edu/dataset/502/online+retail+ii
File   : online_retail_II.xlsx  (two sheets: "Year 2009-2010", "Year 2010-2011")
Content: ~1,067,371 rows of real transactions from a UK-based online giftware
         retailer, 01/12/2009 - 09/12/2011.

Put the .xlsx in  data_raw/  and run:

    python clean_online_retail.py --profile     # just report what is wrong with it
    python clean_online_retail.py               # clean it and build the 7 tables

Output goes to data_real/ so it never overwrites the synthetic data/ folder.

--------------------------------------------------------------------------------------
WHY THIS FILE EXISTS
--------------------------------------------------------------------------------------
The raw file is a single flat sheet and it is genuinely dirty. Every cleaning step
below exists because I found the problem by profiling the data first, not because a
tutorial told me to. The --profile mode prints the evidence for each one.

--------------------------------------------------------------------------------------
TWO THINGS I HAD TO MODEL RATHER THAN MEASURE - stated up front, also in the README
--------------------------------------------------------------------------------------
1. COST. The file has a selling Price but no cost. Profit margin therefore cannot be
   measured from this data. I apply a documented cost model: each derived category
   gets a relative margin (giftware is high-margin, postage/bulk is thin), and the
   whole set is then scaled by one factor so the blended margin lands on TARGET_MARGIN.
   The *relative* differences are my judgement; the *level* is an assumption.

2. CURRENCY. The retailer invoices in GBP. I convert to EUR at a single fixed rate
   (GBP_TO_EUR) rather than a daily rate, because the analysis is about customer
   behaviour, not FX. The rate is roughly the 2010-2011 average.
--------------------------------------------------------------------------------------
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

# ======================================================================================
# CONFIG
# ======================================================================================
HERE = os.path.dirname(os.path.abspath(__file__))
RAW_PATH = os.path.join(HERE, "..", "data_raw", "online_retail_II.xlsx")
OUT_DIR = os.path.join(HERE, "..", "data_real")

GBP_TO_EUR = 1.15          # fixed rate, see note above
TARGET_MARGIN = 0.20       # blended gross margin the cost model is calibrated to

# --------------------------------------------------------------------------------------
# ANALYSIS SCOPE - three decisions, each made after looking at the data
# --------------------------------------------------------------------------------------
# 1. Exclude the UK. The retailer is UK-based, so the UK is 91% of all rows and
#    16.0M EUR of the 19.2M EUR total. Reporting the export business separately is a
#    split the company itself would make, and it is the segment where retention is
#    actually a question.
HOME_MARKET = "United Kingdom"

# 2. Exclude EIRE. Three accounts generate EUR 674,618 - 21.5% of all export revenue
#    from 3 customers out of 518. That is a wholesale/distribution relationship, not
#    the export retail behaviour I am analysing, and leaving it in would dominate every
#    customer-level metric. Excluded and documented rather than quietly left in.
EXCLUDED_MARKETS = ["EIRE"]

# 3. Complete months only. The raw file stops mid-month on 2011-12-09, so December 2011
#    is a partial month. Leaving it in makes the final point of every month-over-month
#    trend line collapse for no real reason. Scope therefore ends 2011-11-30.
SCOPE_END_EXCLUSIVE = "2011-12-01"

# Stock codes that are not products - postage, fees, adjustments, test rows.
NON_PRODUCT_CODES = {
    "POST", "DOT", "C2", "M", "S", "B", "D", "CRUK", "PADS", "GIFT", "TEST001",
    "TEST002", "AMAZONFEE", "BANK CHARGES", "ADJUST", "ADJUST2", "SP1002",
    "DCGSSBOY", "DCGSSGIRL", "DCGS0076", "DCGS0003", "gift_0001_10",
}

PRICE_CEILING = 2000.0     # above this it is an adjustment, not a sale
QTY_CEILING = 2000         # above this it is a wholesale/data-entry anomaly


# ======================================================================================
# CATEGORY DERIVATION
# ======================================================================================
# The raw file has no category column - only a free-text Description. Deriving a
# category from it is what makes category-level margin analysis possible at all.
# Order matters: the first pattern that matches wins, so the specific ones
# (Christmas, Party) are checked before the generic ones (Home Decor).
CATEGORY_RULES = [
    ("Christmas & Seasonal", 0.34, [
        "CHRISTMAS", "XMAS", "ADVENT", "SANTA", "REINDEER", "SNOWMAN", "EASTER",
        "HALLOWEEN", "NATIVITY", "MISTLETOE", "STOCKING"]),
    ("Party & Celebration", 0.32, [
        "PARTY", "BUNTING", "BALLOON", "GARLAND", "BIRTHDAY", "WEDDING", "CONFETTI",
        "GIFT WRAP", "WRAP ", "RIBBON", "GREETING CARD", "CAKE STAND", "PLACEMAT"]),
    ("Kitchen & Dining", 0.24, [
        "MUG", "CUP", "PLATE", "BOWL", "TEAPOT", "CAKE", "BAKING", "CUTLERY", "JUG",
        "KITCHEN", "TRAY", "NAPKIN", "TEA TOWEL", "APRON", "EGG", "JAM", "COOK",
        "BOTTLE", "LUNCH BOX", "CHOPPING", "COASTER", "SPOON", "TIN"]),
    ("Bags & Storage", 0.26, [
        "BAG", "BASKET", "STORAGE", "JAR", "BOX", "CASE", "TRUNK", "CRATE",
        "HOLDALL", "SATCHEL", "PURSE", "WALLET"]),
    ("Home Decor & Lighting", 0.30, [
        "T-LIGHT", "TEA LIGHT", "LANTERN", "CANDLE", "HOLDER", "FRAME", "MIRROR",
        "CLOCK", "ORNAMENT", "HEART", "CUSHION", "VASE", "DECORATION", "WALL",
        "DOORMAT", "HOOK", "LAMP", "LIGHT", "CHANDELIER", "DRAWER", "SIGN",
        "HANGING", "CABINET", "STAND"]),
    ("Stationery & Craft", 0.28, [
        "NOTEBOOK", "PEN ", "PENCIL", "PAPER", "CRAFT", "STICKER", "CHALK", "RUBBER",
        "ERASER", "JOURNAL", "POSTCARD", "NOTE", "CARD ", "ENVELOPE", "SKETCH",
        "PAINT", "GLITTER", "KIT"]),
    ("Toys & Games", 0.29, [
        "TOY", "GAME", "PUZZLE", "DOLL", "PLAYHOUSE", "SKIPPING", "SPACEBOY",
        "SOLDIER", "BINGO", "SNAKES", "TEDDY", "BEAR", "RATTLE", "SPINNING"]),
    ("Garden & Outdoor", 0.22, [
        "GARDEN", "PLANT", "FLOWER", "WATERING", "BIRD", "HERB", "SEED", "PARASOL",
        "WINDMILL", "BUCKET", "TROWEL", "FLOWERPOT"]),
    ("Bath & Beauty", 0.27, [
        "SOAP", "BATH", "TOWEL", "TOILET", "SPONGE", "FLANNEL", "MIRROR COMPACT",
        "PERFUME", "LOTION", "TISSUE"]),
    ("Textiles & Accessories", 0.25, [
        "SCARF", "GLOVE", "HAT", "UMBRELLA", "SLIPPER", "JEWELLERY", "NECKLACE",
        "BRACELET", "EARRING", "RING", "BROOCH", "APRON ", "BLANKET", "THROW"]),
]
FALLBACK_CATEGORY = ("General Merchandise", 0.23)


def derive_category(description: str) -> str:
    """Map a free-text product description onto one of the categories above."""
    if not isinstance(description, str):
        return FALLBACK_CATEGORY[0]
    d = description.upper()
    for name, _margin, keywords in CATEGORY_RULES:
        for kw in keywords:
            if kw in d:
                return name
    return FALLBACK_CATEGORY[0]


CATEGORY_MARGINS = {name: margin for name, margin, _ in CATEGORY_RULES}
CATEGORY_MARGINS[FALLBACK_CATEGORY[0]] = FALLBACK_CATEGORY[1]

CATEGORY_DEPARTMENTS = {
    "Christmas & Seasonal": "Seasonal",
    "Party & Celebration": "Seasonal",
    "Kitchen & Dining": "Home",
    "Bags & Storage": "Home",
    "Home Decor & Lighting": "Home",
    "Stationery & Craft": "Lifestyle",
    "Toys & Games": "Lifestyle",
    "Garden & Outdoor": "Outdoor",
    "Bath & Beauty": "Lifestyle",
    "Textiles & Accessories": "Lifestyle",
    "General Merchandise": "Home",
}


# ======================================================================================
# LOAD
# ======================================================================================
def load_raw() -> pd.DataFrame:
    if not os.path.exists(RAW_PATH):
        sys.exit(
            f"\nERROR: cannot find {os.path.abspath(RAW_PATH)}\n\n"
            "Download 'online_retail_II.xlsx' from\n"
            "  https://archive.ics.uci.edu/dataset/502/online+retail+ii\n"
            "and put it in the data_raw/ folder, then run this script again.\n"
        )
    print("Reading the Excel file (both sheets - this takes about a minute)...")
    sheets = pd.read_excel(RAW_PATH, sheet_name=None, engine="openpyxl")
    df = pd.concat(sheets.values(), ignore_index=True)
    # The two sheets use slightly different column names between releases.
    df = df.rename(columns={
        "Customer ID": "CustomerID", "customer id": "CustomerID",
        "InvoiceNo": "Invoice", "UnitPrice": "Price",
    })
    print(f"Loaded {len(df):,} raw rows from {len(sheets)} sheets.")
    return df


# ======================================================================================
# PROFILE - the evidence for every cleaning decision
# ======================================================================================
def profile_raw(df: pd.DataFrame) -> None:
    n = len(df)
    inv = df["Invoice"].astype(str)

    print("\n" + "=" * 74)
    print(" RAW DATA PROFILE - what is wrong with this file")
    print("=" * 74)
    print(f" Total rows                          : {n:>12,}")
    print(f" Date range                          : "
          f"{df['InvoiceDate'].min()}  ->  {df['InvoiceDate'].max()}")
    print(f" Unique invoices                     : {inv.nunique():>12,}")
    print(f" Unique stock codes                  : {df['StockCode'].nunique():>12,}")
    print(f" Unique customers (excl. missing)    : {df['CustomerID'].nunique():>12,}")
    print("-" * 74)
    print(" PROBLEMS FOUND")
    print("-" * 74)
    dup = df.duplicated().sum()
    miss_cust = df["CustomerID"].isna().sum()
    miss_desc = df["Description"].isna().sum()
    cancels = inv.str.upper().str.startswith("C").sum()
    neg_qty = (df["Quantity"] <= 0).sum()
    zero_price = (df["Price"] <= 0).sum()
    huge_price = (df["Price"] > PRICE_CEILING).sum()
    huge_qty = (df["Quantity"].abs() > QTY_CEILING).sum()
    non_prod = df["StockCode"].astype(str).str.strip().str.upper().isin(NON_PRODUCT_CODES).sum()

    def line(label, count):
        print(f" {label:<36}: {count:>12,}  ({100.0 * count / n:5.2f}%)")

    line("Exact duplicate rows", dup)
    line("Rows with no Customer ID", miss_cust)
    line("Rows with no Description", miss_desc)
    line("Cancellation invoices (start 'C')", cancels)
    line("Quantity <= 0", neg_qty)
    line("Price <= 0", zero_price)
    line(f"Price > {PRICE_CEILING:,.0f} (adjustments)", huge_price)
    line(f"|Quantity| > {QTY_CEILING:,}", huge_qty)
    line("Non-product codes (POST, DOT, M...)", non_prod)

    print("-" * 74)
    print(" Top 12 countries by row count:")
    for country, cnt in df["Country"].value_counts().head(12).items():
        print(f"   {country:<28} {cnt:>10,}")
    print("=" * 74)


# ======================================================================================
# CLEAN
# ======================================================================================
class CleaningLog:
    """Records how many rows each step removed, so the README can quote real numbers."""

    def __init__(self, start_rows):
        self.rows = [("Raw rows loaded", start_rows, start_rows)]
        self.prev = start_rows

    def step(self, label, df):
        now = len(df)
        self.rows.append((label, self.prev - now, now))
        self.prev = now
        return df

    def report(self):
        print("\n" + "=" * 74)
        print(" CLEANING LOG")
        print("=" * 74)
        print(f" {'Step':<44}{'Removed':>12}{'Remaining':>14}")
        print("-" * 74)
        for label, removed, remaining in self.rows:
            rm = "-" if removed == 0 and label.startswith("Raw") else f"{removed:,}"
            print(f" {label:<44}{rm:>12}{remaining:>14,}")
        print("=" * 74)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    log = CleaningLog(len(df))

    # --- normalise text before anything else, so comparisons behave -------------------
    df["Invoice"] = df["Invoice"].astype(str).str.strip().str.upper()
    df["StockCode"] = df["StockCode"].astype(str).str.strip().str.upper()
    df["Description"] = df["Description"].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    df["Country"] = df["Country"].astype(str).str.strip()

    # --- 1. exact duplicates ---------------------------------------------------------
    # Same invoice, same product, same quantity, same timestamp. These are data-entry
    # artefacts, and leaving them in inflates revenue.
    df = log.step("Dropped exact duplicate rows", df.drop_duplicates())

    # --- 2. split off cancellations BEFORE filtering on quantity ---------------------
    # A 'C' invoice is a cancelled/returned order and carries negative quantities.
    # I keep them (as Returned) because returns are the revenue-leakage story, but
    # they must never count towards headline revenue.
    is_cancel = df["Invoice"].str.startswith("C")
    cancels = df[is_cancel].copy()
    df = df[~is_cancel].copy()
    log.step("Split out cancellation invoices ('C')", df)

    # --- 3. rows we genuinely cannot use ---------------------------------------------
    df = log.step("Dropped rows with no Customer ID", df.dropna(subset=["CustomerID"]))
    df = log.step("Dropped rows with no Description",
                  df[(df["Description"] != "") & (df["Description"].str.lower() != "nan")])

    # --- 4. non-product lines --------------------------------------------------------
    # POST = postage, DOT = dotcom postage, M = manual, BANK CHARGES, TEST rows...
    # These are real rows but they are not merchandise, so they distort product and
    # category analysis.
    df = log.step("Dropped non-product stock codes",
                  df[~df["StockCode"].isin(NON_PRODUCT_CODES)])
    # Codes that are pure letters (e.g. 'AMAZONFEE' variants) are also not products.
    df = log.step("Dropped non-numeric stock codes",
                  df[df["StockCode"].str.match(r"^\d{5}")])

    # --- 5. impossible / outlier values ----------------------------------------------
    df = log.step("Dropped Price <= 0", df[df["Price"] > 0])
    df = log.step("Dropped Quantity <= 0", df[df["Quantity"] > 0])
    df = log.step(f"Dropped Price > {PRICE_CEILING:,.0f}", df[df["Price"] <= PRICE_CEILING])
    df = log.step(f"Dropped Quantity > {QTY_CEILING:,}", df[df["Quantity"] <= QTY_CEILING])

    # --- 6. scope (see the three documented decisions at the top of this file) --------
    df = log.step(f"Excluded home market ({HOME_MARKET})",
                  df[df["Country"] != HOME_MARKET])
    df = log.step(f"Excluded wholesale market ({', '.join(EXCLUDED_MARKETS)})",
                  df[~df["Country"].isin(EXCLUDED_MARKETS)])
    df = log.step("Trimmed partial final month (complete months only)",
                  df[pd.to_datetime(df["InvoiceDate"]) < SCOPE_END_EXCLUSIVE])

    # --- clean the cancellations the same way, then merge them back in ---------------
    cancels["Quantity"] = cancels["Quantity"].abs()
    cancels = cancels.dropna(subset=["CustomerID"])
    cancels = cancels[
        (cancels["Price"] > 0)
        & (cancels["Price"] <= PRICE_CEILING)
        & (cancels["Quantity"] <= QTY_CEILING)
        & (~cancels["StockCode"].isin(NON_PRODUCT_CODES))
        & (cancels["StockCode"].str.match(r"^\d{5}"))
        & (cancels["Country"] != HOME_MARKET)
        & (~cancels["Country"].isin(EXCLUDED_MARKETS))
        & (pd.to_datetime(cancels["InvoiceDate"]) < SCOPE_END_EXCLUSIVE)
    ].copy()

    df["order_status"] = "Completed"
    cancels["order_status"] = "Returned"
    out = pd.concat([df, cancels], ignore_index=True)
    log.step("Added cleaned return lines back in", out)

    # --- 7. consolidate repeated product lines within one invoice --------------------
    # 128 invoices list the same stock code on more than one line (a price correction,
    # or the picker scanning the same item twice). That is not wrong in the source
    # system, but my fact table is meant to be one line per product per order, and
    # duplicate keys would double-count that product in any product-level analysis.
    #
    # I sum the quantities and take the revenue-weighted average price, so the total
    # value of the invoice is unchanged - only the number of rows shrinks.
    out["_line_value"] = out["Price"] * out["Quantity"]
    out = out.groupby(["Invoice", "StockCode", "order_status"], as_index=False).agg(
        Description=("Description", "first"),
        Quantity=("Quantity", "sum"),
        _line_value=("_line_value", "sum"),
        InvoiceDate=("InvoiceDate", "min"),
        CustomerID=("CustomerID", "first"),
        Country=("Country", "first"),
    )
    out["Price"] = (out["_line_value"] / out["Quantity"]).round(4)
    out = out.drop(columns=["_line_value"])
    log.step("Consolidated repeated lines within an invoice", out)

    log.report()
    return out


# ======================================================================================
# BUILD THE 7-TABLE STAR SCHEMA
# ======================================================================================
def build_star_schema(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["CustomerID"] = df["CustomerID"].astype(int)
    df["order_date"] = pd.to_datetime(df["InvoiceDate"]).dt.normalize()

    # ---- money: GBP -> EUR -----------------------------------------------------------
    df["unit_price"] = (df["Price"] * GBP_TO_EUR).round(2)

    # ---- category --------------------------------------------------------------------
    df["category_name"] = df["Description"].map(derive_category)

    # ---- dim_categories --------------------------------------------------------------
    cat_names = sorted(df["category_name"].unique())
    cat_ids = {name: i + 1 for i, name in enumerate(cat_names)}

    # Calibrate the cost model: scale every category's margin by one factor so the
    # blended margin across actual sales lands on TARGET_MARGIN.
    completed = df[df["order_status"] == "Completed"]
    rev_by_cat = (completed["unit_price"] * completed["Quantity"]).groupby(
        completed["category_name"]).sum()
    weighted = sum(rev_by_cat.get(c, 0) * CATEGORY_MARGINS[c] for c in cat_names)
    blended = weighted / rev_by_cat.sum() if rev_by_cat.sum() else TARGET_MARGIN
    scale = TARGET_MARGIN / blended
    applied_margin = {c: CATEGORY_MARGINS[c] * scale for c in cat_names}
    print(f"\nCost model: relative margins scaled by {scale:.4f} "
          f"so the blended margin lands on {TARGET_MARGIN:.1%}.")

    dim_categories = pd.DataFrame({
        "category_id": [cat_ids[c] for c in cat_names],
        "category_name": cat_names,
        "department": [CATEGORY_DEPARTMENTS.get(c, "Home") for c in cat_names],
        "target_margin_pct": [round(applied_margin[c] * 100, 2) for c in cat_names],
    })

    # ---- dim_products ----------------------------------------------------------------
    # One row per stock code. A few stock codes carry several spellings of the same
    # description over time, so I take the most frequent one.
    prod = (df.groupby("StockCode")
              .agg(product_name=("Description", lambda s: s.mode().iat[0]),
                   unit_price=("unit_price", "median"),
                   launch_date=("order_date", "min"))
              .reset_index())
    prod["category_name"] = prod["product_name"].map(derive_category)
    prod["category_id"] = prod["category_name"].map(cat_ids)
    prod["unit_price"] = prod["unit_price"].round(2)
    prod["unit_cost"] = (prod["unit_price"]
                         * prod["category_name"].map(applied_margin).rsub(1)).round(2)
    prod["brand"] = "Own Brand"          # the raw data has no brand column
    prod = prod.reset_index(drop=True)
    prod["product_id"] = prod.index + 1
    stock_to_pid = dict(zip(prod["StockCode"], prod["product_id"]))
    dim_products = prod[["product_id", "product_name", "category_id", "brand",
                         "unit_price", "unit_cost", "launch_date"]].copy()
    dim_products["launch_date"] = dim_products["launch_date"].dt.date

    # ---- dim_stores (markets) --------------------------------------------------------
    # This retailer is online-only, so there are no physical stores. The closest real
    # equivalent in this data is the destination market, so dim_stores holds one row
    # per country. Keeping the table name means every downstream SQL query and DAX
    # measure works unchanged against either dataset.
    countries = sorted(df["Country"].unique())
    dim_stores = pd.DataFrame({
        "store_id": range(1, len(countries) + 1),
        "store_name": [f"{c} (Online Export)" for c in countries],
        "channel": "Online",
        "city": countries,
        "country": countries,
        "region": "International Export",
        "opened_date": df["order_date"].min().date(),
    })
    country_to_sid = dict(zip(dim_stores["country"], dim_stores["store_id"]))

    # ---- dim_customers ---------------------------------------------------------------
    # The raw file has no signup date, so I use each customer's first purchase date.
    # That is the standard substitute and it is exactly what the cohort analysis needs.
    cust = (df.groupby("CustomerID")
              .agg(signup_date=("order_date", "min"),
                   country=("Country", lambda s: s.mode().iat[0]))
              .reset_index()
              .rename(columns={"CustomerID": "customer_id"}))
    n_orders = df[df["order_status"] == "Completed"].groupby("CustomerID")["Invoice"].nunique()
    cust["first_name"] = "Customer"
    cust["last_name"] = cust["customer_id"].astype(str)
    cust["email"] = "cust" + cust["customer_id"].astype(str) + "@anonymised.invalid"
    cust["gender"] = ""            # not present in the raw data
    cust["birth_date"] = ""        # not present in the raw data
    cust["age_band"] = "Unknown"   # not present in the raw data
    cust["city"] = cust["country"]
    cust["acquisition_channel"] = "Online Export"   # not present in the raw data
    cust["is_loyalty_member"] = (cust["customer_id"].map(n_orders).fillna(0) >= 3).astype(int)
    cust["signup_date"] = cust["signup_date"].dt.date
    dim_customers = cust[["customer_id", "first_name", "last_name", "email", "gender",
                          "birth_date", "age_band", "city", "country", "signup_date",
                          "acquisition_channel", "is_loyalty_member"]]

    # ---- fact_orders -----------------------------------------------------------------
    df["product_id"] = df["StockCode"].map(stock_to_pid)
    df["store_id"] = df["Country"].map(country_to_sid)
    orders = (df.groupby("Invoice")
                .agg(customer_id=("CustomerID", "first"),
                     store_id=("store_id", "first"),
                     order_date=("order_date", "min"),
                     order_status=("order_status", "first"),
                     n_items=("StockCode", "size"))
                .reset_index())
    orders = orders.sort_values("order_date").reset_index(drop=True)
    orders["order_id"] = orders.index + 1
    invoice_to_oid = dict(zip(orders["Invoice"], orders["order_id"]))
    orders["payment_method"] = "Unknown"   # not present in the raw data
    orders["shipping_cost"] = 0.0          # postage rows were removed as non-product
    orders["order_date"] = orders["order_date"].dt.date
    fact_orders = orders[["order_id", "customer_id", "store_id", "order_date",
                          "order_status", "payment_method", "shipping_cost", "n_items"]]

    # ---- fact_order_items ------------------------------------------------------------
    items = df.copy()
    items["order_id"] = items["Invoice"].map(invoice_to_oid)
    items["unit_cost"] = (items["unit_price"]
                          * items["category_name"].map(applied_margin).rsub(1)).round(2)
    items["quantity"] = items["Quantity"].astype(int)
    items["discount_pct"] = 0.0            # the raw data has no discount column
    items["gross_amount"] = (items["unit_price"] * items["quantity"]).round(2)
    items["discount_amount"] = 0.0
    items["line_revenue"] = items["gross_amount"]
    items["line_cost"] = (items["unit_cost"] * items["quantity"]).round(2)
    items["line_profit"] = (items["line_revenue"] - items["line_cost"]).round(2)
    items = items.sort_values(["order_id"]).reset_index(drop=True)
    items["order_item_id"] = items.index + 1
    fact_order_items = items[["order_item_id", "order_id", "product_id", "quantity",
                              "unit_price", "unit_cost", "discount_pct", "gross_amount",
                              "discount_amount", "line_revenue", "line_cost",
                              "line_profit"]]

    # ---- dim_date --------------------------------------------------------------------
    rng = pd.date_range(df["order_date"].min(), df["order_date"].max(), freq="D")
    dim_date = pd.DataFrame({"full_date": rng})
    dim_date["date_key"] = dim_date["full_date"].dt.strftime("%Y%m%d").astype(int)
    dim_date["year"] = dim_date["full_date"].dt.year
    dim_date["quarter"] = "Q" + dim_date["full_date"].dt.quarter.astype(str)
    dim_date["month_number"] = dim_date["full_date"].dt.month
    dim_date["month_name"] = dim_date["full_date"].dt.strftime("%B")
    dim_date["year_month"] = dim_date["full_date"].dt.strftime("%Y-%m")
    dim_date["week_of_year"] = dim_date["full_date"].dt.isocalendar().week.astype(int)
    dim_date["day_of_month"] = dim_date["full_date"].dt.day
    dim_date["day_name"] = dim_date["full_date"].dt.strftime("%A")
    dim_date["is_weekend"] = (dim_date["full_date"].dt.weekday >= 5).astype(int)
    dim_date["full_date"] = dim_date["full_date"].dt.date
    dim_date = dim_date[["date_key", "full_date", "year", "quarter", "month_number",
                         "month_name", "year_month", "week_of_year", "day_of_month",
                         "day_name", "is_weekend"]]

    return {
        "dim_date": dim_date,
        "dim_customers": dim_customers,
        "dim_categories": dim_categories,
        "dim_products": dim_products,
        "dim_stores": dim_stores,
        "fact_orders": fact_orders,
        "fact_order_items": fact_order_items,
    }


# ======================================================================================
# SUMMARY
# ======================================================================================
def summarise(tables: dict) -> None:
    items = tables["fact_order_items"]
    orders = tables["fact_orders"]
    merged = items.merge(orders[["order_id", "customer_id", "order_status"]], on="order_id")
    done = merged[merged["order_status"] == "Completed"]

    revenue = done["line_revenue"].sum()
    profit = done["line_profit"].sum()
    leaked = merged[merged["order_status"] != "Completed"]["line_revenue"].sum()

    by_cust = done.groupby("customer_id")["line_revenue"].sum().sort_values(ascending=False)
    n_cust = len(by_cust)
    total = by_cust.sum()
    top10 = by_cust.iloc[:int(n_cust * 0.10)].sum() / total * 100
    top20 = by_cust.iloc[:int(n_cust * 0.20)].sum() / total * 100
    top30 = by_cust.iloc[:int(n_cust * 0.30)].sum() / total * 100

    n_orders_per_cust = done.groupby("customer_id")["order_id"].nunique()
    repeat = (n_orders_per_cust >= 2).sum()

    print("\n" + "=" * 66)
    print(" REAL DATASET SUMMARY  (Online Retail II, export markets)")
    print("=" * 66)
    print(f" Customers                 : {len(tables['dim_customers']):>12,}")
    print(f" Products                  : {len(tables['dim_products']):>12,}")
    print(f" Categories                : {len(tables['dim_categories']):>12,}")
    print(f" Markets (dim_stores)      : {len(tables['dim_stores']):>12,}")
    print(f" Orders                    : {len(orders):>12,}")
    print(f" Order items (transactions): {len(items):>12,}")
    print(f" Date range                : {tables['dim_date']['full_date'].min()}"
          f" -> {tables['dim_date']['full_date'].max()}")
    print("-" * 66)
    print(f" Total revenue (completed) : EUR {revenue:>12,.0f}")
    print(f" Total profit  (modelled)  : EUR {profit:>12,.0f}")
    print(f" Profit margin (modelled)  : {profit / revenue * 100:>15.1f} %")
    print(f" Revenue lost to returns   : EUR {leaked:>12,.0f}")
    print("-" * 66)
    print(" Revenue concentration (measured, not modelled):")
    print(f"   top 10% of customers    : {top10:>15.1f} %")
    print(f"   top 20% of customers    : {top20:>15.1f} %")
    print(f"   top 30% of customers    : {top30:>15.1f} %")
    print(f" Purchasing customers      : {n_cust:>12,}")
    print(f" Repeat customers (2+)     : {repeat:>12,}  ({repeat / n_cust * 100:.1f}%)")
    print(f" Avg order value           : EUR "
          f"{revenue / done['order_id'].nunique():>12,.2f}")
    print("=" * 66)


# ======================================================================================
# MAIN
# ======================================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", action="store_true",
                    help="only profile the raw file, do not clean or write anything")
    args = ap.parse_args()

    raw = load_raw()

    if args.profile:
        profile_raw(raw)
        return

    profile_raw(raw)
    cleaned = clean(raw)
    tables = build_star_schema(cleaned)

    os.makedirs(OUT_DIR, exist_ok=True)
    for name, table in tables.items():
        path = os.path.join(OUT_DIR, f"{name}.csv")
        table.to_csv(path, index=False, encoding="utf-8")

    summarise(tables)
    print(f"\n CSV files written to: {os.path.abspath(OUT_DIR)}")
    print(" Load them with sql/01_schema.sql + sql/02_load_data.sql "
          "(point the \\copy paths at data_real/).")


if __name__ == "__main__":
    main()
