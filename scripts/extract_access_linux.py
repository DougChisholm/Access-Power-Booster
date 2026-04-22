"""
extract_access_linux.py
-----------------------
Step 1 — Access DB Extraction (Linux version using mdbtools)

Uses mdbtools CLI utilities to extract tables, columns, and data
from an Access (.accdb/.mdb) database on Linux.

Exports:
  - Schema → /data/schema/<table>.json
  - Data   → /data/tables/<table>.csv

Requirements:
  sudo apt-get install mdbtools

Usage:
  python extract_access_linux.py --db ../input/Database3.accdb
"""

import argparse
import csv
import io
import json
import logging
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("extract_access.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# mdbtools type → friendly name mapping (align with original script output)
# ---------------------------------------------------------------------------
MDB_TYPE_MAP = {
    "Boolean":        "Boolean",
    "Byte":           "Byte",
    "Integer":        "Integer",
    "Long Integer":   "Long",
    "Currency":       "Currency",
    "Single":         "Single",
    "Double":         "Double",
    "DateTime":       "DateTime",
    "Binary":         "Binary",
    "Text":           "Text",
    "OLE":            "LongBinary",
    "Memo":           "Memo",
    "Numeric":        "Decimal",
    "Replication ID":  "Guid",
    "Complex":        "ComplexText",
}


def run_mdb(cmd: list[str], db_path: str) -> str:
    """Run an mdbtools command and return stdout."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except FileNotFoundError:
        log.error("mdbtools not found. Install with: sudo apt-get install mdbtools")
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        log.error("Command %s failed: %s", " ".join(cmd), exc.stderr)
        raise


def list_user_tables(db_path: str) -> list[str]:
    """Return all user-defined table names."""
    output = run_mdb(["mdb-tables", "-1", db_path], db_path)
    tables = [
        t.strip() for t in output.strip().split("\n")
        if t.strip()
        and not t.strip().startswith("MSys")
        and not t.strip().startswith("~")
    ]
    log.info("Found %d user tables: %s", len(tables), tables)
    return tables


def get_columns(db_path: str, table: str) -> list[dict]:
    """Return column metadata for a table using mdb-schema."""
    output = run_mdb(["mdb-schema", "--table", table, db_path], db_path)
    cols = []
    ordinal = 1

    # Parse CREATE TABLE from mdb-schema output
    in_create = False
    for line in output.split("\n"):
        line = line.strip()

        if line.upper().startswith("CREATE TABLE"):
            in_create = True
            continue

        if in_create and line == ");":
            break

        if in_create and line and not line.startswith("("):
            # Remove trailing comma
            line = line.rstrip(",").strip()

            # Parse: [column_name]   type(size)  [NOT NULL]
            match = re.match(
                r'\[(.+?)\]\s+(\w[\w\s]*?)(?:\s*\((\d+)\))?'
                r'(\s+NOT\s+NULL)?',
                line,
            )
            if match:
                col_name = match.group(1)
                raw_type = match.group(2).strip()
                max_length = int(match.group(3)) if match.group(3) else None
                nullable = match.group(4) is None

                friendly_type = MDB_TYPE_MAP.get(raw_type, raw_type)

                col = {
                    "name": col_name,
                    "type": friendly_type,
                    "mdb_type": raw_type,
                    "max_length": max_length,
                    "nullable": nullable,
                    "ordinal": ordinal,
                }
                cols.append(col)
                ordinal += 1

    return cols


def get_primary_keys(db_path: str, table: str) -> list[str]:
    """Attempt to extract primary keys from mdb-schema output."""
    output = run_mdb(["mdb-schema", "--table", table, db_path], db_path)
    pks = []

    # Look for: ALTER TABLE ... ADD CONSTRAINT ... PRIMARY KEY (col1, col2)
    # or inline PRIMARY KEY in CREATE TABLE
    for line in output.split("\n"):
        pk_match = re.search(r'PRIMARY\s+KEY\s*\((.+?)\)', line, re.IGNORECASE)
        if pk_match:
            pk_cols = pk_match.group(1)
            for col in pk_cols.split(","):
                col = col.strip().strip("[]")
                if col:
                    pks.append(col)

    return pks


def get_relationships(db_path: str) -> list[dict]:
    """Extract relationships using mdb-schema with relationship options."""
    relationships = []

    # Try to get relationships from full schema
    try:
        output = run_mdb(["mdb-schema", db_path], db_path)
    except Exception:
        return relationships

    # Parse ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ... REFERENCES ...
    for line in output.split("\n"):
        fk_match = re.search(
            r'ALTER\s+TABLE\s+\[(.+?)\]\s+ADD\s+CONSTRAINT\s+.+?'
            r'FOREIGN\s+KEY\s*\(\[(.+?)\]\)\s*'
            r'REFERENCES\s+\[(.+?)\]\s*\(\[(.+?)\]\)',
            line, re.IGNORECASE,
        )
        if fk_match:
            relationships.append({
                "fk_table": fk_match.group(1),
                "fk_column": fk_match.group(2),
                "pk_table": fk_match.group(3),
                "pk_column": fk_match.group(4),
            })

    log.info("Detected %d relationships", len(relationships))
    return relationships


def export_schema(db_path: str, tables: list[str], schema_dir: str) -> dict:
    """Export per-table schema JSON files. Returns full schema dict."""
    os.makedirs(schema_dir, exist_ok=True)
    full_schema = {}

    for table in tables:
        pks = get_primary_keys(db_path, table)
        cols = get_columns(db_path, table)
        table_schema = {
            "table_name": table,
            "primary_keys": pks,
            "columns": cols,
        }
        full_schema[table] = table_schema

        out_file = os.path.join(schema_dir, f"{table}.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(table_schema, f, indent=2)
        log.info("Schema written: %s", out_file)

    relationships = get_relationships(db_path)
    rel_file = os.path.join(schema_dir, "_relationships.json")
    with open(rel_file, "w", encoding="utf-8") as f:
        json.dump(relationships, f, indent=2)
    log.info("Relationships written: %s", rel_file)

    full_schema["_relationships"] = relationships
    return full_schema


def export_table_data(db_path: str, table: str, tables_dir: str) -> int:
    """Export all rows of a table to CSV using mdb-export. Returns row count."""
    os.makedirs(tables_dir, exist_ok=True)

    output = run_mdb(["mdb-export", db_path, table], db_path)
    out_file = os.path.join(tables_dir, f"{table}.csv")

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(output)

    # Count rows (subtract 1 for header)
    row_count = max(0, output.strip().count("\n"))
    log.info("Exported %d rows → %s", row_count, out_file)
    return row_count


def main():
    parser = argparse.ArgumentParser(
        description="Extract Access DB schema and data (Linux/mdbtools)"
    )
    parser.add_argument(
        "--db", default="../input/Database3.accdb",
        help="Path to .accdb/.mdb file",
    )
    parser.add_argument(
        "--schema-dir", default="../data/schema",
        help="Output dir for schema JSON",
    )
    parser.add_argument(
        "--tables-dir", default="../data/tables",
        help="Output dir for CSV data",
    )
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.isfile(db_path):
        log.error("Access database not found: %s", db_path)
        sys.exit(1)

    log.info("Using mdbtools to extract from: %s", db_path)

    tables = list_user_tables(db_path)
    if not tables:
        log.warning("No user tables found in the database.")
        sys.exit(0)

    log.info("=== Exporting schema ===")
    schema = export_schema(db_path, tables, args.schema_dir)

    log.info("=== Exporting table data ===")
    total_rows = 0
    for table in tables:
        total_rows += export_table_data(db_path, table, args.tables_dir)

    log.info(
        "Extraction complete. %d tables, %d total rows.",
        len(tables), total_rows,
    )
    print("\n✅ Extraction complete.")
    print(f"   Schema → {os.path.abspath(args.schema_dir)}")
    print(f"   Data   → {os.path.abspath(args.tables_dir)}")


if __name__ == "__main__":
    main()
