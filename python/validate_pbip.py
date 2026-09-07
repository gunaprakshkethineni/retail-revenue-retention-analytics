"""
validate_pbip.py
----------------
Checks the generated model.bim before you open it in Power BI.

It cannot tell you the .pbip format is right - only Power BI can do that - but it does
catch the failure I was actually worried about: a measure referring to a table or
column that does not exist. In Power BI that shows up as a vague error on load with no
indication of which measure is at fault.

    python validate_pbip.py
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "..", "powerbi", "RetailAnalytics.SemanticModel", "model.bim")

# Table[Column] references in DAX. Bare [Measure] references are checked separately.
QUALIFIED_REF = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]")
BARE_REF = re.compile(r"(?<![A-Za-z0-9_\]])\[([^\]]+)\]")

# DAX functions that take a table name without brackets.
KNOWN_FUNCTIONS = {
    "ALL", "ALLEXCEPT", "ALLSELECTED", "VALUES", "DISTINCT", "FILTER", "RELATEDTABLE",
    "COUNTROWS", "SUMX", "AVERAGEX", "MAXX", "MINX", "RANKX", "ADDCOLUMNS",
}


def main():
    with open(MODEL, encoding="utf-8") as f:
        model = json.load(f)

    tables = {}
    measures = {}
    for table in model["model"]["tables"]:
        tables[table["name"]] = {c["name"] for c in table.get("columns", [])}
        for measure in table.get("measures", []):
            measures[measure["name"]] = "\n".join(measure["expression"])

    print("=" * 72)
    print(" MODEL CONTENTS")
    print("=" * 72)
    for table in model["model"]["tables"]:
        calc = [c["name"] for c in table.get("columns", []) if c.get("type") == "calculated"]
        n_measures = len(table.get("measures", []))
        line = f"  {table['name']:<20} {len(table.get('columns', [])):>3} cols"
        if calc:
            line += f"  ({len(calc)} calculated)"
        if n_measures:
            line += f"  {n_measures} measures"
        if table.get("dataCategory") == "Time":
            line += "   [marked as date table]"
        print(line)
        for name in calc:
            print(f"      + {name}")

    print("\n" + "=" * 72)
    print(" RELATIONSHIPS")
    print("=" * 72)
    errors = []
    for rel in model["model"]["relationships"]:
        ok = True
        for side in ("from", "to"):
            t, c = rel[f"{side}Table"], rel[f"{side}Column"]
            if t not in tables or c not in tables[t]:
                errors.append(f"relationship references missing {t}[{c}]")
                ok = False
        flag = "OK " if ok else "BAD"
        print(f"  {flag} {rel['fromTable']}[{rel['fromColumn']}]"
              f"  ->  {rel['toTable']}[{rel['toColumn']}]")

    print("\n" + "=" * 72)
    print(" DAX REFERENCE CHECK")
    print("=" * 72)

    def check(expression, label):
        found = []
        for table, column in QUALIFIED_REF.findall(expression):
            if table.upper() in KNOWN_FUNCTIONS:
                continue
            if table not in tables:
                found.append(f"unknown table '{table}' in {table}[{column}]")
            elif column not in tables[table]:
                found.append(f"unknown column {table}[{column}]")
        # Bare [Name] must be an existing measure.
        stripped = QUALIFIED_REF.sub(" ", expression)
        for name in BARE_REF.findall(stripped):
            if name not in measures:
                found.append(f"unknown measure [{name}]")
        for problem in found:
            errors.append(f"{label}: {problem}")
        return found

    checked = 0
    for table in model["model"]["tables"]:
        for column in table.get("columns", []):
            if column.get("type") == "calculated":
                checked += 1
                for problem in check("\n".join(column["expression"]),
                                     f"column {table['name']}[{column['name']}]"):
                    print(f"  BAD  {table['name']}[{column['name']}]: {problem}")
        for measure in table.get("measures", []):
            checked += 1
            for problem in check("\n".join(measure["expression"]), f"measure [{measure['name']}]"):
                print(f"  BAD  [{measure['name']}]: {problem}")

    print(f"  Checked {checked} DAX expressions.")

    print("\n" + "=" * 72)
    if errors:
        print(f" {len(errors)} PROBLEM(S) FOUND")
        print("=" * 72)
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print(" No broken references. Model is internally consistent.")
    print("=" * 72)


if __name__ == "__main__":
    main()
