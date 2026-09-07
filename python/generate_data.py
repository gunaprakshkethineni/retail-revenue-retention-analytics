"""
generate_data.py
----------------
Builds the synthetic retail dataset used by this project.

I could not use a real company's sales data (privacy + it is not mine to publish),
so I wrote this generator to produce a realistic European retail dataset that
behaves the way retail data actually behaves:

  * revenue is heavily concentrated in a small group of customers (Pareto effect)
  * most customers buy once and never come back (the drop-off problem)
  * margin differs a lot per category (grocery is thin, fashion is fat)
  * some orders are returned or cancelled -> revenue leakage

Output: 7 CSV files in ../data/ that map 1:1 to the 7 SQL tables in ../sql/01_schema.sql

Run:  python generate_data.py
Only the Python standard library is used, so there is nothing to pip install.
"""

import csv
import math
import os
import random
from datetime import date, timedelta

# --------------------------------------------------------------------------------------
# CONFIG - the knobs I tuned until the dataset behaved like real retail data
#
# I did not get these on the first try. I wrote the generator, ran it, looked at the
# summary at the bottom, changed one number, and ran it again - probably forty times.
# The hard part was that the knobs fight each other: turning up SPEND_SIGMA to get more
# one-time buyers also makes revenue MORE concentrated, so I had to find a middle.
# --------------------------------------------------------------------------------------
def cfg(name, default, cast=float):
    """Lets me override a knob from the command line while I calibrate the dataset."""
    return cast(os.environ.get(name, default))


SEED = cfg("SEED", 20240517, int)

N_CUSTOMERS = cfg("N_CUSTOMERS", 13_000, int)
N_PRODUCTS = cfg("N_PRODUCTS", 320, int)

START_DATE = date(2023, 1, 1)
END_DATE = date(2024, 12, 31)
LAST_SIGNUP_DATE = date(2024, 9, 30)  # so the newest cohorts still have time to repeat

# Customer value spread. Higher sigma = more inequality between customers.
# This is what drives the "top 30% of customers = 60% of revenue" finding.
SPEND_SIGMA = cfg("SPEND_SIGMA", 0.30)

BASE_REPEAT_LAMBDA = cfg("REPEAT_LAMBDA", 1.30)  # avg extra orders for an average customer
REPEAT_GAP_MEAN_DAYS = cfg("REPEAT_GAP", 78)     # average days between two orders
BASKET_LAMBDA = cfg("BASKET_LAMBDA", 1.45)       # how many distinct products land in a basket
BASKET_W_EXP = cfg("BASKET_W_EXP", 0.0)          # how much basket size follows customer value
PRICE_SKEW = cfg("PRICE_SKEW", 2.00)             # higher = catalogue skews to cheaper SKUs

RETURN_RATE = cfg("RETURN_RATE", 0.032)   # share of orders returned
CANCEL_RATE = cfg("CANCEL_RATE", 0.015)   # share of orders cancelled before fulfilment

WRITE_CSV = os.environ.get("NO_WRITE") != "1"   # off while calibrating

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

random.seed(SEED)


# --------------------------------------------------------------------------------------
# Small helpers (no numpy, so I wrote the samplers myself)
# --------------------------------------------------------------------------------------
def poisson(lam: float) -> int:
    """Knuth's algorithm. Fine here because lambda always stays small."""
    if lam <= 0:
        return 0
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= random.random()
        if p <= L:
            return k
        k += 1


def weighted_choice(items, weights):
    return random.choices(items, weights=weights, k=1)[0]


def money(x: float) -> float:
    return round(x + 1e-9, 2)


def rand_date(a: date, b: date) -> date:
    return a + timedelta(days=random.randint(0, (b - a).days))


# --------------------------------------------------------------------------------------
# 1. dim_categories
# --------------------------------------------------------------------------------------
# margin = gross margin on the list price.
# I made Grocery deliberately thin and Electronics mid, because those two carry most of
# the revenue and they are what drags the blended company margin down to about 20%. If I
# had given every category a fat margin the overall number would have been unrealistic -
# real supermarkets make very little on the things people buy most often.
CATEGORY_SPEC = [
    # name,                    department,      margin, price_lo, price_hi, popularity
    ("Electronics",            "Technology",     0.165,   29.0,  549.0,  1.00),
    ("Home & Kitchen",         "Home",           0.285,    9.0,  199.0,  1.15),
    ("Fashion & Apparel",      "Lifestyle",      0.345,   12.0,  139.0,  1.30),
    ("Beauty & Personal Care", "Lifestyle",      0.325,    4.5,   79.0,  1.25),
    ("Sports & Outdoors",      "Lifestyle",      0.260,   14.0,  229.0,  0.80),
    ("Toys & Games",           "Home",           0.295,    6.0,   99.0,  0.70),
    ("Grocery & Beverages",    "Everyday",       0.135,    1.6,   35.0,  1.55),
    ("Books & Stationery",     "Everyday",       0.220,    3.5,   49.0,  0.85),
]

categories = []
for i, (name, dept, margin, lo, hi, pop) in enumerate(CATEGORY_SPEC, start=1):
    categories.append(
        {
            "category_id": i,
            "category_name": name,
            "department": dept,
            "target_margin_pct": round(margin * 100, 1),
        }
    )

cat_meta = {i: CATEGORY_SPEC[i - 1] for i in range(1, len(CATEGORY_SPEC) + 1)}


# --------------------------------------------------------------------------------------
# 2. dim_stores
# --------------------------------------------------------------------------------------
STORE_SPEC = [
    ("Berlin Mitte Flagship", "In-Store", "Berlin",    "Germany",     "DACH-North", date(2019, 3, 11)),
    ("Munich Zentrum",        "In-Store", "Munich",    "Germany",     "DACH-South", date(2020, 9,  1)),
    ("Hamburg Hafen",         "In-Store", "Hamburg",   "Germany",     "DACH-North", date(2021, 6, 15)),
    ("Vienna Ringstrasse",    "In-Store", "Vienna",    "Austria",     "DACH-South", date(2021, 11, 4)),
    ("Amsterdam Centraal",    "In-Store", "Amsterdam", "Netherlands", "Benelux",    date(2022, 4, 22)),
    ("Online Store EU",       "Online",   "Berlin",    "Germany",     "E-Commerce", date(2018, 1,  8)),
]
# The online store takes the biggest share of orders, like most retailers post-2020.
STORE_WEIGHTS = [0.13, 0.11, 0.09, 0.08, 0.07, 0.52]

stores = []
for i, (name, channel, city, country, region, opened) in enumerate(STORE_SPEC, start=1):
    stores.append(
        {
            "store_id": i,
            "store_name": name,
            "channel": channel,
            "city": city,
            "country": country,
            "region": region,
            "opened_date": opened.isoformat(),
        }
    )
store_ids = [s["store_id"] for s in stores]


# --------------------------------------------------------------------------------------
# 3. dim_products
# --------------------------------------------------------------------------------------
BRANDS = [
    "Nordwerk", "Casavia", "Lumora", "Peakline", "Verdemio", "Basiq",
    "Ottone", "Kraftwerk Co", "Milane", "Halvorsen", "Fjordly", "Aurelia",
]
PRODUCT_NOUNS = {
    1: ["Wireless Earbuds", "Bluetooth Speaker", "4K Monitor", "Laptop Sleeve", "Smart Watch",
        "Power Bank", "USB-C Hub", "Mechanical Keyboard", "Noise-Cancelling Headset", "Action Camera"],
    2: ["Ceramic Cookware Set", "Espresso Machine", "Storage Basket", "LED Floor Lamp", "Cutlery Set",
        "Air Fryer", "Bedding Set", "Wall Clock", "Vacuum Flask", "Knife Block"],
    3: ["Merino Sweater", "Rain Jacket", "Slim Jeans", "Linen Shirt", "Wool Scarf",
        "Running Sneakers", "Leather Belt", "Chino Trousers", "Puffer Vest", "Cotton T-Shirt"],
    4: ["Vitamin C Serum", "Shampoo Bar", "Electric Toothbrush", "Hand Cream", "Perfume 50ml",
        "Face Cleanser", "Beard Trimmer", "Body Lotion", "Sunscreen SPF50", "Lip Balm Set"],
    5: ["Yoga Mat", "Trekking Backpack", "Dumbbell Pair", "Cycling Helmet", "Camping Tent",
        "Football", "Water Bottle 1L", "Resistance Band Set", "Trail Running Shoes", "Sleeping Bag"],
    6: ["Building Blocks Set", "Board Game", "Plush Bear", "Puzzle 1000pc", "RC Car",
        "Art Supplies Kit", "Wooden Train Set", "Card Game", "Science Kit", "Doll House"],
    7: ["Arabica Coffee 1kg", "Olive Oil 750ml", "Dark Chocolate Bar", "Sparkling Water 6pk", "Pasta 500g",
        "Green Tea Box", "Muesli 750g", "Honey Jar", "Almond Milk 1L", "Protein Bar Box"],
    8: ["Hardcover Novel", "Notebook A5", "Fountain Pen", "Desk Planner", "Cookbook",
        "Sticky Notes Pack", "Business Paperback", "Sketchbook", "Highlighter Set", "Travel Guide"],
}

products = []
product_pop_weights = []
pid = 0
# Spread the 320 products across categories, roughly by how popular the category is.
cat_product_counts = {}
total_pop = sum(c[5] for c in CATEGORY_SPEC)
for cid, (name, dept, margin, lo, hi, pop) in enumerate(CATEGORY_SPEC, start=1):
    cat_product_counts[cid] = max(20, round(N_PRODUCTS * pop / total_pop))

for cid, n_prod in cat_product_counts.items():
    _, _, margin, lo, hi, _ = cat_meta[cid]
    for j in range(n_prod):
        pid += 1
        noun = random.choice(PRODUCT_NOUNS[cid])
        brand = random.choice(BRANDS)
        # Prices are skewed on a log scale: lots of cheap SKUs, a few expensive ones.
        u = random.random() ** PRICE_SKEW
        price = money(lo * (hi / lo) ** u)
        # Every product has its own margin around the category target.
        prod_margin = min(0.62, max(0.05, random.gauss(margin, 0.045)))
        cost = money(price * (1 - prod_margin))
        products.append(
            {
                "product_id": pid,
                "product_name": f"{brand} {noun}",
                "category_id": cid,
                "brand": brand,
                "unit_price": price,
                "unit_cost": cost,
                "launch_date": rand_date(date(2018, 1, 1), date(2024, 6, 30)).isoformat(),
            }
        )
        # Within a category a handful of SKUs are bestsellers (long-tail effect).
        product_pop_weights.append(random.lognormvariate(0, 0.85))

N_PRODUCTS_ACTUAL = len(products)
product_by_id = {p["product_id"]: p for p in products}

# Sampling weight for a product = category popularity x its own popularity
product_sample_weights = [
    product_pop_weights[i] * cat_meta[products[i]["category_id"]][5]
    for i in range(N_PRODUCTS_ACTUAL)
]
product_ids = [p["product_id"] for p in products]


# --------------------------------------------------------------------------------------
# 4. dim_customers
# --------------------------------------------------------------------------------------
FIRST_NAMES = [
    "Lukas", "Anna", "Jonas", "Marie", "Felix", "Lena", "Paul", "Sofia", "Elias", "Emma",
    "Noah", "Mia", "Ben", "Hannah", "Leon", "Klara", "Jan", "Nora", "Tim", "Julia",
    "Matteo", "Laura", "Samuel", "Ida", "David", "Elena", "Moritz", "Alina", "Niklas", "Greta",
]
LAST_NAMES = [
    "Muller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker",
    "Hoffmann", "Schafer", "Koch", "Bauer", "Richter", "Klein", "Wolf", "Neumann",
    "De Vries", "Jansen", "Bakker", "Visser", "Novak", "Horvath", "Berger", "Gruber",
]
CITY_SPEC = [
    ("Berlin", "Germany"), ("Munich", "Germany"), ("Hamburg", "Germany"),
    ("Cologne", "Germany"), ("Frankfurt", "Germany"), ("Stuttgart", "Germany"),
    ("Vienna", "Austria"), ("Graz", "Austria"),
    ("Amsterdam", "Netherlands"), ("Rotterdam", "Netherlands"),
]
CHANNELS = ["Paid Search", "Organic Search", "Social Ads", "Email Campaign", "Referral", "Walk-in"]
CHANNEL_WEIGHTS = [0.24, 0.21, 0.18, 0.12, 0.10, 0.15]

customers = []
cust_weight = {}
for cid in range(1, N_CUSTOMERS + 1):
    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)
    city, country = random.choice(CITY_SPEC)
    birth = rand_date(date(1958, 1, 1), date(2006, 12, 31))
    age = (END_DATE - birth).days // 365
    if age < 25:
        band = "18-24"
    elif age < 35:
        band = "25-34"
    elif age < 45:
        band = "35-44"
    elif age < 55:
        band = "45-54"
    elif age < 65:
        band = "55-64"
    else:
        band = "65+"

    signup = rand_date(START_DATE, LAST_SIGNUP_DATE)
    customers.append(
        {
            "customer_id": cid,
            "first_name": fn,
            "last_name": ln,
            "email": f"{fn.lower()}.{ln.lower().replace(' ', '')}{cid}@example.com",
            "gender": random.choice(["F", "M", "X"]) if random.random() > 0.02 else "X",
            "birth_date": birth.isoformat(),
            "age_band": band,
            "city": city,
            "country": country,
            "signup_date": signup.isoformat(),
            "acquisition_channel": weighted_choice(CHANNELS, CHANNEL_WEIGHTS),
            "is_loyalty_member": 0,  # set later - loyalty follows behaviour, not the other way round
        }
    )
    # This single number decides how valuable the customer will be.
    cust_weight[cid] = random.lognormvariate(0, SPEND_SIGMA)

customer_by_id = {c["customer_id"]: c for c in customers}


# --------------------------------------------------------------------------------------
# 5 + 6. fact_orders and fact_order_items
# --------------------------------------------------------------------------------------
PAYMENT_METHODS = ["Credit Card", "PayPal", "SEPA Direct Debit", "Klarna", "Cash", "Apple Pay"]
PAYMENT_WEIGHTS = [0.30, 0.22, 0.16, 0.13, 0.09, 0.10]

orders = []
order_items = []
order_id = 0
item_id = 0

# Mild seasonality: November/December spike, February dip.
MONTH_FACTOR = {1: 0.88, 2: 0.82, 3: 0.95, 4: 0.97, 5: 1.00, 6: 1.02,
                7: 0.98, 8: 0.94, 9: 1.03, 10: 1.08, 11: 1.28, 12: 1.35}


def build_order_dates(signup: date, w: float):
    """First order on signup day, then repeat orders until the customer churns."""
    dates = [signup]
    n_repeat = poisson(BASE_REPEAT_LAMBDA * w)
    cursor = signup
    for _ in range(n_repeat):
        gap = int(random.expovariate(1 / REPEAT_GAP_MEAN_DAYS)) + 5
        cursor = cursor + timedelta(days=gap)
        if cursor > END_DATE:
            break
        # Seasonality: a bit more likely to keep an order that lands in a peak month.
        if random.random() > MONTH_FACTOR[cursor.month] * 0.78:
            continue
        dates.append(cursor)
    return dates


for c in customers:
    cid = c["customer_id"]
    w = cust_weight[cid]
    signup = date.fromisoformat(c["signup_date"])

    for od in build_order_dates(signup, w):
        order_id += 1
        store_id = weighted_choice(store_ids, STORE_WEIGHTS)

        r = random.random()
        if r < CANCEL_RATE:
            status = "Cancelled"
        elif r < CANCEL_RATE + RETURN_RATE:
            status = "Returned"
        else:
            status = "Completed"

        n_lines = 1 + poisson(BASKET_LAMBDA * (w ** BASKET_W_EXP))
        n_lines = min(n_lines, 8)

        chosen = set()
        lines_written = 0
        for _ in range(n_lines):
            p = weighted_choice(product_ids, product_sample_weights)
            if p in chosen:
                continue
            chosen.add(p)
            prod = product_by_id[p]

            # Cheap items get bought in bigger quantities.
            if prod["unit_price"] < 15:
                qty = random.choices([1, 2, 3, 4, 5], weights=[30, 28, 20, 13, 9])[0]
            elif prod["unit_price"] < 80:
                qty = random.choices([1, 2, 3], weights=[68, 24, 8])[0]
            else:
                qty = random.choices([1, 2], weights=[90, 10])[0]

            # Discounts: most lines full price, promo lines get 10-30% off.
            d = random.random()
            if d < 0.62:
                disc = 0.0
            elif d < 0.86:
                disc = round(random.uniform(0.05, 0.15), 2)
            else:
                disc = round(random.uniform(0.15, 0.30), 2)
            # December promo push
            if od.month == 12 and random.random() < 0.35:
                disc = max(disc, round(random.uniform(0.10, 0.25), 2))

            gross = prod["unit_price"] * qty
            revenue = money(gross * (1 - disc))
            cost = money(prod["unit_cost"] * qty)

            item_id += 1
            lines_written += 1
            order_items.append(
                {
                    "order_item_id": item_id,
                    "order_id": order_id,
                    "product_id": p,
                    "quantity": qty,
                    "unit_price": prod["unit_price"],
                    "unit_cost": prod["unit_cost"],
                    "discount_pct": disc,
                    "gross_amount": money(gross),
                    "discount_amount": money(gross - revenue),
                    "line_revenue": revenue,
                    "line_cost": cost,
                    "line_profit": money(revenue - cost),
                }
            )

        if lines_written == 0:      # extremely rare, but never leave an empty order
            order_id -= 1
            continue

        shipping = 0.0
        if store_id == 6:  # online orders can carry shipping
            shipping = 0.0 if random.random() < 0.62 else round(random.choice([3.99, 4.99, 5.99]), 2)

        orders.append(
            {
                "order_id": order_id,
                "customer_id": cid,
                "store_id": store_id,
                "order_date": od.isoformat(),
                "order_status": status,
                "payment_method": weighted_choice(PAYMENT_METHODS, PAYMENT_WEIGHTS),
                "shipping_cost": shipping,
                "n_items": lines_written,
            }
        )

# Loyalty flag: customers with 3+ orders are much more likely to be members.
orders_per_cust = {}
for o in orders:
    orders_per_cust[o["customer_id"]] = orders_per_cust.get(o["customer_id"], 0) + 1
for c in customers:
    n = orders_per_cust.get(c["customer_id"], 0)
    p_member = 0.08 if n <= 1 else (0.28 if n == 2 else 0.66)
    c["is_loyalty_member"] = 1 if random.random() < p_member else 0


# --------------------------------------------------------------------------------------
# 7. dim_date
# --------------------------------------------------------------------------------------
MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

dim_date = []
d = START_DATE
while d <= END_DATE:
    dim_date.append(
        {
            "date_key": int(d.strftime("%Y%m%d")),
            "full_date": d.isoformat(),
            "year": d.year,
            "quarter": f"Q{(d.month - 1) // 3 + 1}",
            "month_number": d.month,
            "month_name": MONTH_NAMES[d.month - 1],
            "year_month": d.strftime("%Y-%m"),
            "week_of_year": int(d.strftime("%V")),
            "day_of_month": d.day,
            "day_name": DAY_NAMES[d.weekday()],
            "is_weekend": 1 if d.weekday() >= 5 else 0,
        }
    )
    d += timedelta(days=1)


# --------------------------------------------------------------------------------------
# Write CSVs
# --------------------------------------------------------------------------------------
def write_csv(filename, rows):
    path = os.path.join(OUT_DIR, filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


if WRITE_CSV:
    os.makedirs(OUT_DIR, exist_ok=True)
    write_csv("dim_date.csv", dim_date)
    write_csv("dim_customers.csv", customers)
    write_csv("dim_categories.csv", categories)
    write_csv("dim_products.csv", products)
    write_csv("dim_stores.csv", stores)
    write_csv("fact_orders.csv", orders)
    write_csv("fact_order_items.csv", order_items)


# --------------------------------------------------------------------------------------
# Sanity check - print the same KPIs the dashboard is supposed to show
# --------------------------------------------------------------------------------------
status_by_order = {o["order_id"]: o["order_status"] for o in orders}
cust_by_order = {o["order_id"]: o["customer_id"] for o in orders}

total_rev = total_cost = 0.0
lost_rev = 0.0
rev_by_cust = {}
for it in order_items:
    st = status_by_order[it["order_id"]]
    if st == "Completed":
        total_rev += it["line_revenue"]
        total_cost += it["line_cost"]
        cu = cust_by_order[it["order_id"]]
        rev_by_cust[cu] = rev_by_cust.get(cu, 0.0) + it["line_revenue"]
    else:
        lost_rev += it["line_revenue"]

profit = total_rev - total_cost
ranked = sorted(rev_by_cust.values(), reverse=True)
top30_n = int(len(ranked) * 0.30)
top30_share = sum(ranked[:top30_n]) / sum(ranked) * 100

repeat_customers = sum(1 for n in orders_per_cust.values() if n >= 2)
repeat_rate = repeat_customers / len(rev_by_cust) * 100

if os.environ.get("TUNE") == "1":
    print(
        f"sigma={SPEND_SIGMA:.2f} lam={BASE_REPEAT_LAMBDA:.2f} basket={BASKET_LAMBDA:.2f} "
        f"bexp={BASKET_W_EXP:.2f} skew={PRICE_SKEW:.2f} | "
        f"items={len(order_items):>6,} rev={total_rev/1e6:>5.2f}M "
        f"margin={profit/total_rev*100:>4.1f}% top30={top30_share:>4.1f}% "
        f"repeat={repeat_rate:>4.1f}% aov={total_rev / sum(1 for o in orders if o['order_status'] == 'Completed'):>6.2f}"
    )
    raise SystemExit(0)

print("=" * 62)
print(" DATASET SUMMARY")
print("=" * 62)
print(f" Customers                 : {len(customers):>12,}")
print(f" Products                  : {len(products):>12,}")
print(f" Orders                    : {len(orders):>12,}")
print(f" Order items (transactions): {len(order_items):>12,}")
print(f" Date range                : {START_DATE} -> {END_DATE}")
print("-" * 62)
print(f" Total revenue (completed) : EUR {total_rev:>12,.0f}")
print(f" Total cost                : EUR {total_cost:>12,.0f}")
print(f" Total profit              : EUR {profit:>12,.0f}")
print(f" Profit margin             : {profit / total_rev * 100:>15.1f} %")
print(f" Revenue lost to returns/  : EUR {lost_rev:>12,.0f}")
print(f"   cancellations")
print("-" * 62)
print(f" Top 30% customers revenue : {top30_share:>15.1f} %")
print(f" Purchasing customers      : {len(rev_by_cust):>12,}")
print(f" Repeat customers (2+)     : {repeat_customers:>12,}  ({repeat_rate:.1f}%)")
print(f" Avg order value           : EUR {total_rev / sum(1 for o in orders if o['order_status'] == 'Completed'):>12,.2f}")
print("=" * 62)
print(f" CSV files written to: {os.path.abspath(OUT_DIR)}")
