"""
extract_access_reports.py
-------------------------
Extracts queries (saved SQL) and report metadata from an Access database
using mdbtools, and suggests Power Platform equivalents.

Outputs:
  - data/schema/_queries.json    — saved queries with SQL
  - data/schema/_reports.json    — report names (metadata only)
  - data/schema/_migration_guide.json — mapping suggestions

Requirements:
  sudo apt-get install mdbtools

Usage:
  python extract_access_reports.py --db ../input/Database3.accdb
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def run_cmd(cmd: list[str]) -> str:
    """Run a command and return stdout."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return result.stdout
    except FileNotFoundError:
        log.error("mdbtools not found. Install with: sudo apt-get install mdbtools")
        sys.exit(1)


def extract_queries(db_path: str) -> list[dict]:
    """Extract saved queries using mdb-queries."""
    queries = []

    # mdb-queries lists query names
    output = run_cmd(["mdb-queries", db_path])
    query_names = [q.strip() for q in output.strip().split("\n") if q.strip()]

    if not query_names:
        log.info("No saved queries found.")
        return queries

    log.info("Found %d queries: %s", len(query_names), query_names)

    # Get SQL for each query using mdb-schema with query type
    for name in query_names:
        sql = ""
        # mdb-sql can execute a query; mdb-schema --query shows CREATE VIEW
        schema_output = run_cmd(["mdb-schema", db_path, "--table", name])
        if "CREATE VIEW" in schema_output or "SELECT" in schema_output.upper():
            sql = schema_output.strip()

        query_info = {
            "name": name,
            "sql": sql,
            "type": classify_query(name, sql),
        }
        queries.append(query_info)
        log.info("  Query: %s (%s)", name, query_info["type"])

    return queries


def classify_query(name: str, sql: str) -> str:
    """Classify a query as select/aggregate/action based on SQL content."""
    sql_upper = sql.upper()
    if "GROUP BY" in sql_upper or "SUM(" in sql_upper or "COUNT(" in sql_upper or "AVG(" in sql_upper:
        return "aggregate"
    if "INSERT" in sql_upper or "UPDATE" in sql_upper or "DELETE" in sql_upper:
        return "action"
    if "CROSSTAB" in sql_upper or "PIVOT" in sql_upper or "TRANSFORM" in sql_upper:
        return "crosstab"
    return "select"


def extract_report_names(db_path: str) -> list[dict]:
    """
    Extract report object names from the Access database.
    mdbtools has limited report support — we extract what we can.
    """
    reports = []

    # mdb-tables with system tables can reveal MSysObjects entries for reports
    # Reports are type 32768 in MSysObjects
    output = run_cmd(["mdb-export", db_path, "MSysObjects"])
    if not output.strip():
        log.info("Could not read MSysObjects for report metadata.")
        return reports

    # Parse CSV output to find report objects (Type = -32764 for reports)
    import csv
    import io

    reader = csv.DictReader(io.StringIO(output))
    for row in reader:
        obj_type = row.get("Type", "")
        obj_name = row.get("Name", "")
        # Access object types: -32764 = Report, -32766 = Form, -32768 = Module
        if obj_type in ("-32764",):
            reports.append({
                "name": obj_name,
                "type": "Report",
            })
        elif obj_type in ("-32768",):
            reports.append({
                "name": obj_name,
                "type": "Module",
            })
        elif obj_type in ("-32766",):
            reports.append({
                "name": obj_name,
                "type": "Form",
            })

    log.info("Found %d Access objects (reports/forms/modules): %s",
             len(reports), [r["name"] for r in reports])
    return reports


def generate_migration_guide(queries: list[dict], reports: list[dict]) -> dict:
    """Generate migration suggestions for each query/report."""
    guide = {
        "summary": {
            "total_queries": len(queries),
            "total_reports": len([r for r in reports if r["type"] == "Report"]),
            "total_forms": len([r for r in reports if r["type"] == "Form"]),
        },
        "query_migration": [],
        "report_migration": [],
    }

    for q in queries:
        suggestion = {
            "access_name": q["name"],
            "access_type": q["type"],
        }
        if q["type"] == "select":
            suggestion["power_platform_target"] = "Dataverse View (SavedQuery)"
            suggestion["alternative"] = "Power BI dataset or FetchXML query"
            suggestion["notes"] = "Create a Dataverse view with equivalent filters/columns, or use Power BI for more complex needs."
        elif q["type"] == "aggregate":
            suggestion["power_platform_target"] = "Power BI Report"
            suggestion["alternative"] = "Dataverse rollup column or calculated column"
            suggestion["notes"] = "Aggregate queries map best to Power BI visuals or Dataverse rollup fields."
        elif q["type"] == "crosstab":
            suggestion["power_platform_target"] = "Power BI Matrix visual"
            suggestion["notes"] = "Crosstab/pivot queries should be recreated as Power BI matrix or pivot table visuals."
        elif q["type"] == "action":
            suggestion["power_platform_target"] = "Power Automate Flow"
            suggestion["notes"] = "Action queries (INSERT/UPDATE/DELETE) should be implemented as Power Automate flows or Dataverse business rules."

        guide["query_migration"].append(suggestion)

    for r in reports:
        if r["type"] == "Report":
            guide["report_migration"].append({
                "access_name": r["name"],
                "power_platform_target": "Power BI Report",
                "alternative": "Model-Driven App SSRS report or paginated report",
                "notes": "Recreate in Power BI connected to the Dataverse tables. Use paginated reports for print-formatted output.",
            })

    return guide


def main():
    parser = argparse.ArgumentParser(
        description="Extract Access queries/reports and generate migration guide"
    )
    parser.add_argument("--db", default="../input/Database3.accdb", help="Path to .accdb")
    parser.add_argument("--output-dir", default="../data/schema", help="Output directory")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.isfile(db_path):
        log.error("Database not found: %s", db_path)
        sys.exit(1)

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Extract queries
    log.info("=== Extracting Queries ===")
    queries = extract_queries(db_path)
    queries_file = os.path.join(output_dir, "_queries.json")
    with open(queries_file, "w", encoding="utf-8") as f:
        json.dump(queries, f, indent=2)
    log.info("Queries written: %s", queries_file)

    # Extract reports/forms
    log.info("=== Extracting Reports & Forms ===")
    reports = extract_report_names(db_path)
    reports_file = os.path.join(output_dir, "_reports.json")
    with open(reports_file, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2)
    log.info("Reports written: %s", reports_file)

    # Generate migration guide
    log.info("=== Generating Migration Guide ===")
    guide = generate_migration_guide(queries, reports)
    guide_file = os.path.join(output_dir, "_migration_guide.json")
    with open(guide_file, "w", encoding="utf-8") as f:
        json.dump(guide, f, indent=2)
    log.info("Migration guide written: %s", guide_file)

    # Print summary
    print("\n✅ Report/query extraction complete.")
    print(f"   Queries : {len(queries)}")
    print(f"   Reports : {guide['summary']['total_reports']}")
    print(f"   Forms   : {guide['summary']['total_forms']}")
    print(f"   Guide   : {guide_file}")

    if queries:
        print("\n📋 Query migration suggestions:")
        for q in guide["query_migration"]:
            print(f"   {q['access_name']} ({q['access_type']}) → {q['power_platform_target']}")

    if guide["report_migration"]:
        print("\n📊 Report migration suggestions:")
        for r in guide["report_migration"]:
            print(f"   {r['access_name']} → {r['power_platform_target']}")


if __name__ == "__main__":
    main()
