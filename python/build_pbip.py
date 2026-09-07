"""
build_pbip.py
-------------
Generates a Power BI Project (.pbip) with the whole semantic model already built:
the 7 tables, their data types, the 6 relationships, dim_date marked as a date table,
and every measure and calculated column from powerbi/measures.dax.

I open the generated .pbip in Power BI Desktop and go straight to building visuals -
the model, the relationships and all the DAX are already in place.

    python build_pbip.py              # uses data_real/  (the cleaned UCI data)
    python build_pbip.py --synthetic  # uses data/       (the generated data)

Output: powerbi/RetailAnalytics.pbip  (plus two folders next to it)

--------------------------------------------------------------------------------------
WHY A GENERATOR AND NOT A HAND-WRITTEN FILE
--------------------------------------------------------------------------------------
A .pbix is a binary zip and cannot sensibly be written by hand. A .pbip is the same
report stored as plain text, which means it can be generated - and, more importantly,
diffed and code-reviewed like any other source file.

Everything here is derived rather than typed out:
  * column names come from the actual CSV headers
  * column data types are inferred from the CSV contents, so a column that is empty
    in one dataset but a date in the other does not break the load
  * measures and calculated columns are PARSED OUT OF measures.dax, so that file stays
    the single source of truth and the two can never drift apart

--------------------------------------------------------------------------------------
IF POWER BI REFUSES TO OPEN THE RESULT
--------------------------------------------------------------------------------------
The .pbip schema shifts between Power BI Desktop versions, so a file written by hand
like this one is tied to the version it was written against. If a newer version rejects
it, run validate_pbip.py first to rule out a broken reference, then rebuild the model in
the UI using measures.dax - the DAX is identical either way, and DASHBOARD_GUIDE.md
lists the relationships and the date-table setting to reproduce.
"""

import argparse
import csv
import json
import os
import re
import uuid
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DAX_FILE = os.path.join(ROOT, "powerbi", "measures.dax")
OUT_DIR = os.path.join(ROOT, "powerbi")
PROJECT_NAME = "RetailAnalytics"

TABLES = [
    "dim_date", "dim_customers", "dim_categories", "dim_products",
    "dim_stores", "fact_orders", "fact_order_items",
]

# from-table (many side) -> to-table (one side)
RELATIONSHIPS = [
    ("fact_orders", "order_date", "dim_date", "full_date"),
    ("fact_orders", "customer_id", "dim_customers", "customer_id"),
    ("fact_orders", "store_id", "dim_stores", "store_id"),
    ("fact_order_items", "order_id", "fact_orders", "order_id"),
    ("fact_order_items", "product_id", "dim_products", "product_id"),
    ("dim_products", "category_id", "dim_categories", "category_id"),
]

# Columns I hide in report view. Nobody building a chart wants to see customer_id or the
# three raw RFM scores in the field list - they want "RFM Segment". Hiding the plumbing
# was the single change that made my own model pleasant to work with.
HIDDEN_COLUMNS = {
    "dim_date": ["date_key"],
    "dim_customers": ["customer_id", "first_name", "last_name", "gender", "birth_date"],
    "dim_categories": ["category_id"],
    "dim_products": ["product_id", "category_id"],
    "dim_stores": ["store_id"],
    "fact_orders": ["order_id", "customer_id", "store_id"],
    "fact_order_items": ["order_item_id", "order_id", "product_id"],
}
HIDDEN_CALC_COLUMNS = {"Recency Days", "R Score", "F Score", "M Score", "First Order Date"}

# Number formats, matched on the measure name. ORDER MATTERS - the first pattern that
# matches wins, so the specific rules have to come before the general ones.
# (My first version put the generic "...Value$" rule first, which caught
#  "Avg Order Value" and formatted it with 0 decimals, and nothing at all matched
#  "Top 30% Revenue Share" because the % is in the middle of the name.)
FORMAT_RULES = [
    (r"^Avg Order Value$", '"€"#,##0.00'),
    # Text measures - must be excluded before the currency rule sees the word "Revenue".
    (r"^(Pareto Page Title|MoM Arrow|Filter Context Footer)$", None),
    (r"(%|Share|Rate)$", "0.0%"),
    (r"(Revenue|Profit|Cost|Given|List Price)", '"€"#,##0'),
    (r"(Customers|Transactions|Orders|Size|Units Sold)$", "#,##0"),
]


# ======================================================================================
# Type inference from the CSV itself
# ======================================================================================
INT_COLUMNS = {
    "quantity", "n_items", "is_weekend", "is_loyalty_member", "year", "month_number",
    "week_of_year", "day_of_month", "date_key",
}
FLOAT_COLUMNS = {
    "unit_price", "unit_cost", "discount_pct", "gross_amount", "discount_amount",
    "line_revenue", "line_cost", "line_profit", "shipping_cost", "target_margin_pct",
}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def infer_types(csv_path):
    """Return {column: (tmsl_type, m_type)} using the header plus a sample of rows."""
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        sample = [row for _, row in zip(range(400), reader)]

    types = {}
    for i, col in enumerate(header):
        values = [r[i] for r in sample if i < len(r) and r[i] != ""]

        if not values:
            # This column is completely empty in this dataset - birth_date is, in the
            # real data, because the source file has no birth dates. I found this when
            # the whole table refused to load: Power BI tried to convert "" to a date and
            # threw an error on every single row. Typing it as text just works.
            types[col] = ("string", "type text")
        elif col.endswith("_id") or col in INT_COLUMNS:
            types[col] = ("int64", "Int64.Type")
        elif col in FLOAT_COLUMNS:
            types[col] = ("double", "type number")
        elif col.endswith("_date") or DATE_RE.match(values[0]):
            types[col] = ("dateTime", "type date")
        else:
            types[col] = ("string", "type text")
    return header, types


# ======================================================================================
# Parse measures.dax
# ======================================================================================
MARKER_RE = re.compile(
    r"^//\s*(?P<kind>[MC])(?P<num>\d+)\s+(?P<tier>CORE|OPTIONAL)(?:\s*-\s*(?P<note>.*))?$"
)


def parse_dax(path):
    """Pull every numbered measure / calculated column out of measures.dax."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    items, current = [], None
    for line in lines:
        marker = MARKER_RE.match(line.strip())
        if marker:
            if current:
                items.append(current)
            note = (marker.group("note") or "").strip()
            table = None
            m = re.search(r"on\s+([A-Za-z_][A-Za-z0-9_]*)", note)
            if m:
                table = m.group(1)
            current = {
                "kind": marker.group("kind"),
                "num": int(marker.group("num")),
                "tier": marker.group("tier"),
                "table": table,
                "body": [],
            }
            continue
        if current is None:
            continue
        # A section divider ends the current block.
        if line.startswith("// ===="):
            items.append(current)
            current = None
            continue
        if line.strip().startswith("//"):
            continue          # explanatory comment inside a block
        current["body"].append(line)
    if current:
        items.append(current)

    parsed = []
    for item in items:
        text = "\n".join(item["body"]).strip()
        if not text:
            continue
        name, _, expression = text.partition("=")
        name = name.strip()
        expression = expression.strip()
        if not name or not expression:
            continue
        item["name"] = name
        item["expression"] = expression
        parsed.append(item)
    return parsed


def format_for(name):
    for pattern, fmt in FORMAT_RULES:
        if re.search(pattern, name):
            return fmt          # may be None for text measures, which is correct
    return None


# ======================================================================================
# Build model.bim (TMSL)
# ======================================================================================
def m_expression(table, header, types):
    """Power Query that reads one CSV out of the DataFolder parameter."""
    transforms = ", ".join(f'{{"{c}", {types[c][1]}}}' for c in header)
    return [
        "let",
        f'    Source = Csv.Document(File.Contents(DataFolder & "\\{table}.csv"),'
        f'[Delimiter=",", Columns={len(header)}, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        f"    Typed = Table.TransformColumnTypes(Promoted,{{{transforms}}})",
        "in",
        "    Typed",
    ]


def build_model(data_dir, dax_items):
    calc_columns = [i for i in dax_items if i["kind"] == "C"]
    measures = [i for i in dax_items if i["kind"] == "M"]

    tables = []
    for table in TABLES:
        csv_path = os.path.join(data_dir, f"{table}.csv")
        header, types = infer_types(csv_path)

        columns = []
        for col in header:
            tmsl_type, _ = types[col]
            column = {
                "name": col,
                "dataType": tmsl_type,
                "sourceColumn": col,
                "summarizeBy": "none",
            }
            if tmsl_type == "dateTime":
                column["formatString"] = "yyyy-mm-dd"
            if col in HIDDEN_COLUMNS.get(table, []):
                column["isHidden"] = True
            # Mark the date key so "Mark as date table" is already applied.
            if table == "dim_date" and col == "full_date":
                column["isKey"] = True
            columns.append(column)

        # Calculated columns belonging to this table.
        for item in calc_columns:
            if item["table"] != table:
                continue
            column = {
                "name": item["name"],
                "type": "calculated",
                "expression": item["expression"].splitlines(),
                "isDataTypeInferred": True,
                "summarizeBy": "none",
            }
            if item["name"] in HIDDEN_CALC_COLUMNS:
                column["isHidden"] = True
            columns.append(column)

        table_def = {
            "name": table,
            "columns": columns,
            "partitions": [
                {
                    "name": table,
                    "mode": "import",
                    "source": {"type": "m", "expression": m_expression(table, header, types)},
                }
            ],
        }
        # This is what "Mark as date table" actually sets.
        if table == "dim_date":
            table_def["dataCategory"] = "Time"

        tables.append(table_def)

    # A dedicated, empty table to hold the measures so they sort to the top of the
    # Fields pane instead of hiding inside the seven real tables.
    measure_defs = []
    for item in measures:
        measure = {
            "name": item["name"],
            "expression": item["expression"].splitlines(),
        }
        fmt = format_for(item["name"])
        if fmt:
            measure["formatString"] = fmt
        measure_defs.append(measure)

    tables.append({
        "name": "_Measures",
        "columns": [
            {
                "name": "Value",
                "dataType": "int64",
                "type": "calculatedTableColumn",
                "sourceColumn": "[Value]",
                "isNameInferred": True,
                "isHidden": True,
                "summarizeBy": "none",
            }
        ],
        "partitions": [
            {
                "name": "_Measures",
                "mode": "import",
                "source": {"type": "calculated", "expression": ["{ BLANK() }"]},
            }
        ],
        "measures": measure_defs,
    })

    relationships = []
    for from_table, from_col, to_table, to_col in RELATIONSHIPS:
        relationships.append({
            "name": str(uuid.uuid4()),
            "fromTable": from_table,
            "fromColumn": from_col,
            "toTable": to_table,
            "toColumn": to_col,
        })

    return {
        "name": PROJECT_NAME,
        "compatibilityLevel": 1567,
        "model": {
            "culture": "en-US",
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "sourceQueryCulture": "en-US",
            "dataAccessOptions": {
                "legacyRedirects": True,
                "returnErrorValuesAsNull": True,
            },
            "expressions": [
                {
                    "name": "DataFolder",
                    "kind": "m",
                    "expression": [
                        f'"{data_dir}" meta [IsParameterQuery=true, Type="Text", '
                        "IsParameterQueryRequired=true]"
                    ],
                }
            ],
            "tables": tables,
            "relationships": relationships,
            "annotations": [
                {"name": "PBI_QueryOrder", "value": json.dumps(TABLES + ["_Measures"])},
                {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"},
            ],
        },
    }


# ======================================================================================
# Build the (deliberately empty) report
# ======================================================================================
PAGES = ["Overview", "Profitability", "Customer Value", "Retention"]


def build_report():
    """Four named, empty pages. The visuals are yours to build - that is the part
    worth learning, and the part an interviewer will ask you about."""
    sections = []
    for i, name in enumerate(PAGES):
        sections.append({
            "name": f"ReportSection{i + 1}",
            "displayName": name,
            "filters": "[]",
            "ordinal": i,
            "visualContainers": [],
            "config": "{}",
            "displayOption": 1,
            "width": 1280,
            "height": 720,
        })
    return {
        "config": json.dumps({
            "version": "5.43",
            "activeSectionIndex": 0,
            "defaultDrillFilterOtherVisuals": True,
            "settings": {"useStylableVisualContainerHeader": True},
        }),
        "layoutOptimization": 0,
        "resourcePackages": [
            {
                "resourcePackage": {
                    "name": "SharedResources",
                    "type": 2,
                    "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": 202}],
                    "disabled": False,
                }
            }
        ],
        "sections": sections,
        "filters": "[]",
    }


def platform_file(kind, name):
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/"
                   "gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": kind, "displayName": name},
        "config": {"version": "2.0", "logicalId": str(uuid.uuid4())},
    }


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ======================================================================================
# Main
# ======================================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true",
                    help="build against data/ instead of data_real/")
    args = ap.parse_args()

    data_dir = os.path.join(ROOT, "data" if args.synthetic else "data_real")
    if not os.path.exists(os.path.join(data_dir, "fact_order_items.csv")):
        raise SystemExit(f"ERROR: no data found in {data_dir}. Generate it first.")

    dax_items = parse_dax(DAX_FILE)
    measures = [i for i in dax_items if i["kind"] == "M"]
    columns = [i for i in dax_items if i["kind"] == "C"]
    if len(measures) < 20 or len(columns) < 10:
        raise SystemExit(
            f"ERROR: only parsed {len(measures)} measures and {len(columns)} columns "
            "out of measures.dax - the file format must have changed."
        )

    orphans = [c["name"] for c in columns if c["table"] not in TABLES]
    if orphans:
        raise SystemExit(f"ERROR: these calculated columns name an unknown table: {orphans}")

    model = build_model(data_dir, dax_items)
    report = build_report()

    model_dir = os.path.join(OUT_DIR, f"{PROJECT_NAME}.SemanticModel")
    report_dir = os.path.join(OUT_DIR, f"{PROJECT_NAME}.Report")

    write_json(os.path.join(OUT_DIR, f"{PROJECT_NAME}.pbip"), {
        "version": "1.0",
        "artifacts": [{"report": {"path": f"{PROJECT_NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })

    write_json(os.path.join(model_dir, ".platform"), platform_file("SemanticModel", PROJECT_NAME))
    write_json(os.path.join(model_dir, "definition.pbism"), {"version": "1.0", "settings": {}})
    write_json(os.path.join(model_dir, "model.bim"), model)

    write_json(os.path.join(report_dir, ".platform"), platform_file("Report", PROJECT_NAME))
    write_json(os.path.join(report_dir, "definition.pbir"), {
        "version": "1.0",
        "datasetReference": {"byPath": {"path": f"../{PROJECT_NAME}.SemanticModel"}},
    })
    write_json(os.path.join(report_dir, "report.json"), report)

    n_calc = sum(
        1 for t in model["model"]["tables"]
        for c in t.get("columns", []) if c.get("type") == "calculated"
    )
    print("=" * 70)
    print(" POWER BI PROJECT GENERATED")
    print("=" * 70)
    print(f"  Dataset            : {'synthetic' if args.synthetic else 'real (UCI)'}")
    print(f"  Data folder        : {data_dir}")
    print(f"  Tables             : {len(model['model']['tables'])} "
          f"(7 data + 1 measures table)")
    print(f"  Relationships      : {len(model['model']['relationships'])}")
    print(f"  Measures           : {len(measures)}")
    print(f"  Calculated columns : {n_calc}")
    print(f"  Report pages       : {len(PAGES)} (empty - visuals are yours to build)")
    print(f"  Generated          : {datetime.now():%Y-%m-%d %H:%M}")
    print("-" * 70)
    print(f"  Open this file in Power BI Desktop:")
    print(f"    {os.path.join(OUT_DIR, PROJECT_NAME + '.pbip')}")
    print("=" * 70)


if __name__ == "__main__":
    main()
