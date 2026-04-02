"""
extract_access.py
-----------------
Step 1 — Access DB Extraction

Connects to an Access (.accdb) database via pyodbc (Windows OLEDB driver),
extracts tables, columns, primary keys, relationships, and data,
then exports:
  - Schema → /data/schema/<table>.json
  - Data   → /data/tables/<table>.csv

Requirements:
  pip install pyodbc
  Microsoft Access Database Engine 2016 Redistributable must be installed.
  Run on Windows only (OLEDB driver).

Usage:
  python extract_access.py --db ../input/Database3.accdb
"""

import argparse
import csv
import json
import logging
import os
import sys

# pyodbc is available only on Windows with the Access OLEDB driver
try:
    import pyodbc
except ImportError:
    print("ERROR: pyodbc not installed. Run: pip install pyodbc")
    sys.exit(1)

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
# Access type → friendly name mapping
# ---------------------------------------------------------------------------
ACCESS_TYPE_MAP = {
    1:  "Boolean",      # Yes/No
    2:  "Byte",
    3:  "Integer",
    4:  "Long",
    5:  "Currency",
    6:  "Single",
    7:  "Double",
    8:  "DateTime",
    9:  "Binary",
    10: "Text",
    11: "LongBinary",   # OLE Object
    12: "Memo",         # Long Text
    14: "Decimal",
    15: "Guid",
    16: "BigInt",
    101: "Attachment",
    102: "ComplexByte",
    103: "ComplexShort",
    104: "ComplexLong",
    105: "ComplexDouble",
    106: "ComplexGuid",
    107: "ComplexDecimal",
    108: "ComplexText",
}

# OLEDB type codes returned by pyodbc cursor.columns()
OLEDB_TYPE_MAP = {
    -11: "Guid",
    -10: "Memo",
    -9:  "Text",
    -8:  "Text",
    -7:  "Boolean",
    -6:  "Byte",
    -5:  "BigInt",
    -4:  "LongBinary",
    -3:  "Binary",
    -2:  "Binary",
    -1:  "Memo",
    1:   "Text",
    2:   "Decimal",
    3:   "Decimal",
    4:   "Long",
    5:   "Integer",
    6:   "Single",
    7:   "Double",
    8:   "Decimal",
    9:   "DateTime",
    10:  "Text",
    11:  "DateTime",
    12:  "Text",
    91:  "DateTime",
    93:  "DateTime",
}


def get_connection(db_path: str) -> pyodbc.Connection:
    """Return an OLEDB connection to the Access database."""
    abs_path = os.path.abspath(db_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Access database not found: {abs_path}")
    conn_str = (
        r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={abs_path};"
    )
    log.info("Connecting to Access DB: %s", abs_path)
    return pyodbc.connect(conn_str, autocommit=True)


def list_user_tables(conn: pyodbc.Connection) -> list[str]:
    """Return all user-defined table names (skip MSys* / ~* system tables)."""
    cursor = conn.cursor()
    tables = [
        row.table_name
        for row in cursor.tables(tableType="TABLE")
        if not row.table_name.startswith("MSys")
        and not row.table_name.startswith("~")
    ]
    log.info("Found %d user tables: %s", len(tables), tables)
    return tables


def get_primary_keys(conn: pyodbc.Connection, table: str) -> list[str]:
    """Return list of primary key column names for a table."""
    cursor = conn.cursor()
    try:
        pk_rows = cursor.primaryKeys(table)
        return [row.column_name for row in pk_rows]
    except Exception:
        return []


def get_columns(conn: pyodbc.Connection, table: str) -> list[dict]:
    """Return column metadata for a table."""
    cursor = conn.cursor()
    cols = []
    for row in cursor.columns(table=table):
        type_name = OLEDB_TYPE_MAP.get(row.data_type, f"Unknown({row.data_type})")
        col = {
            "name": row.column_name,
            "type": type_name,
            "oledb_type_code": row.data_type,
            "max_length": row.column_size,
            "nullable": row.nullable == 1,
            "ordinal": row.ordinal_position,
        }
        cols.append(col)
    return sorted(cols, key=lambda c: c["ordinal"])


def get_relationships(conn: pyodbc.Connection, tables: list[str]) -> list[dict]:
    """
    Attempt to detect FK relationships via cursor.foreignKeys().
    Returns list of {pk_table, pk_column, fk_table, fk_column}.
    """
    relationships = []
    seen = set()
    for table in tables:
        cursor = conn.cursor()
        try:
            for row in cursor.foreignKeys(foreignTable=table):
                key = (row.pktable_name, row.pkcolumn_name, row.fktable_name, row.fkcolumn_name)
                if key not in seen:
                    seen.add(key)
                    relationships.append({
                        "pk_table": row.pktable_name,
                        "pk_column": row.pkcolumn_name,
                        "fk_table": row.fktable_name,
                        "fk_column": row.fkcolumn_name,
                    })
        except Exception as exc:
            log.debug("Could not read FK for table %s: %s", table, exc)
    log.info("Detected %d relationships", len(relationships))
    return relationships


def export_schema(conn: pyodbc.Connection, tables: list[str], schema_dir: str) -> dict:
    """Export per-table schema JSON files. Returns full schema dict."""
    os.makedirs(schema_dir, exist_ok=True)
    full_schema = {}

    for table in tables:
        pks = get_primary_keys(conn, table)
        cols = get_columns(conn, table)
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

    relationships = get_relationships(conn, tables)
    rel_file = os.path.join(schema_dir, "_relationships.json")
    with open(rel_file, "w", encoding="utf-8") as f:
        json.dump(relationships, f, indent=2)
    log.info("Relationships written: %s", rel_file)

    full_schema["_relationships"] = relationships
    return full_schema


def safe_value(val) -> str:
    """Convert a value to a safe CSV string."""
    if val is None:
        return ""
    if isinstance(val, bytes):
        return "<binary>"
    return str(val)


def export_table_data(conn: pyodbc.Connection, table: str, tables_dir: str) -> int:
    """Export all rows of a table to CSV. Returns row count."""
    os.makedirs(tables_dir, exist_ok=True)
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM [{table}]")
    headers = [desc[0] for desc in cursor.description]
    out_file = os.path.join(tables_dir, f"{table}.csv")
    row_count = 0
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in cursor:
            writer.writerow([safe_value(v) for v in row])
            row_count += 1
    log.info("Exported %d rows → %s", row_count, out_file)
    return row_count


def main():
    parser = argparse.ArgumentParser(description="Extract Access DB schema and data")
    parser.add_argument("--db", default="../input/Database3.accdb", help="Path to .accdb file")
    parser.add_argument("--schema-dir", default="../data/schema", help="Output dir for schema JSON")
    parser.add_argument("--tables-dir", default="../data/tables", help="Output dir for CSV data")
    args = parser.parse_args()

    conn = get_connection(args.db)
    tables = list_user_tables(conn)

    if not tables:
        log.warning("No user tables found in the database.")
        sys.exit(0)

    log.info("=== Exporting schema ===")
    schema = export_schema(conn, tables, args.schema_dir)

    log.info("=== Exporting table data ===")
    total_rows = 0
    for table in tables:
        total_rows += export_table_data(conn, table, args.tables_dir)

    conn.close()
    log.info("Extraction complete. %d tables, %d total rows.", len(tables), total_rows)
    print("\n✅ Extraction complete.")
    print(f"   Schema → {os.path.abspath(args.schema_dir)}")
    print(f"   Data   → {os.path.abspath(args.tables_dir)}")


if __name__ == "__main__":
    main()
