"""
migrate_data.py
---------------
Step 4 — Data Migration to Dataverse

Reads CSV files from /data/tables/ and inserts records into Dataverse
via the Web API using batching and retry logic.

Requirements:
  pip install requests msal

Environment variables (or .env file):
  DATAVERSE_URL       e.g. https://yourorg.crm.dynamics.com
  AZURE_CLIENT_ID     Service principal / app registration client ID
  AZURE_CLIENT_SECRET Service principal secret
  AZURE_TENANT_ID     Azure AD tenant ID

Usage:
  python migrate_data.py
  python migrate_data.py --table Customers   # single table only
  python migrate_data.py --dry-run           # validate without inserting
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

try:
    import msal
except ImportError:
    print("ERROR: msal not installed. Run: pip install msal")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("migrate_data.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TABLES_DIR = "../data/tables"
SCHEMA_DIR = "../dataverse/tables"
BATCH_SIZE = 100          # records per $batch request
MAX_RETRIES = 3
RETRY_DELAY = 5           # seconds between retries
API_VERSION = "9.2"

# ---------------------------------------------------------------------------
# Access type → Python converter
# ---------------------------------------------------------------------------
def coerce_value(value: str, access_type: str):
    """Convert a CSV string value to the appropriate Python type."""
    if value == "" or value is None:
        return None
    try:
        if access_type in ("Boolean",):
            return value.lower() in ("true", "yes", "1", "-1")
        if access_type in ("Integer", "Long", "Byte", "BigInt"):
            return int(float(value))
        if access_type in ("Single", "Double", "Decimal", "Currency"):
            return float(value)
        if access_type == "DateTime":
            # Return ISO 8601 string — Dataverse accepts this
            return value if "T" in value else value + "T00:00:00Z"
    except (ValueError, TypeError):
        pass
    return value


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def get_access_token(dataverse_url: str) -> str:
    """Acquire an OAuth2 token using MSAL client credentials."""
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET")

    if not all([tenant_id, client_id, client_secret]):
        raise EnvironmentError(
            "Missing environment variables: AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET"
        )

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    scope = [f"{dataverse_url}/.default"]

    app = msal.ConfidentialClientApplication(
        client_id, authority=authority, client_credential=client_secret
    )
    result = app.acquire_token_for_client(scopes=scope)
    if "access_token" not in result:
        raise RuntimeError(f"Token acquisition failed: {result.get('error_description')}")
    log.info("Access token acquired.")
    return result["access_token"]


# ---------------------------------------------------------------------------
# Dataverse helpers
# ---------------------------------------------------------------------------
def get_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Prefer": "return=representation",
    }


def upsert_record(session: requests.Session, base_url: str, entity_set: str,
                  record: dict, dry_run: bool = False) -> bool:
    """POST a single record to Dataverse. Returns True on success."""
    url = f"{base_url}/api/data/v{API_VERSION}/{entity_set}"
    if dry_run:
        log.debug("[DRY RUN] Would POST to %s: %s", url, record)
        return True

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(url, json=record, timeout=30)
            if resp.status_code in (200, 201, 204):
                return True
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", RETRY_DELAY))
                log.warning("Rate limited. Waiting %ds (attempt %d/%d)", retry_after, attempt, MAX_RETRIES)
                time.sleep(retry_after)
                continue
            log.error("HTTP %d inserting into %s: %s", resp.status_code, entity_set, resp.text[:300])
            return False
        except requests.RequestException as exc:
            log.warning("Request error (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    return False


def send_batch(session: requests.Session, base_url: str, entity_set: str,
               records: list[dict], dry_run: bool = False) -> tuple[int, int]:
    """
    Send a $batch request containing multiple POST operations.
    Returns (success_count, failure_count).
    """
    if dry_run:
        log.info("[DRY RUN] Would batch-insert %d records into %s", len(records), entity_set)
        return len(records), 0

    batch_id = f"batch_{int(time.time())}"
    changeset_id = f"changeset_{int(time.time())}"
    api_url = f"{base_url}/api/data/v{API_VERSION}/{entity_set}"

    body_parts = [f"--{changeset_id}"]
    for record in records:
        body_parts.append(
            "Content-Type: application/http\r\n"
            "Content-Transfer-Encoding: binary\r\n\r\n"
            f"POST {api_url} HTTP/1.1\r\n"
            "Content-Type: application/json;type=entry\r\n\r\n"
            + json.dumps(record)
        )
    body_parts.append(f"--{changeset_id}--")

    batch_body = (
        f"--{batch_id}\r\n"
        f"Content-Type: multipart/mixed; boundary={changeset_id}\r\n\r\n"
        + "\r\n".join(body_parts) + "\r\n"
        + f"--{batch_id}--"
    )

    headers = {
        **session.headers,
        "Content-Type": f"multipart/mixed; boundary={batch_id}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(
                f"{base_url}/api/data/v{API_VERSION}/$batch",
                data=batch_body.encode("utf-8"),
                headers=headers,
                timeout=120,
            )
            if resp.status_code in (200, 202):
                # Count 201s in the response body
                successes = resp.text.count("HTTP/1.1 201")
                failures = len(records) - successes
                return successes, failures
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", RETRY_DELAY))
                log.warning("Rate limited. Waiting %ds", retry_after)
                time.sleep(retry_after)
                continue
            log.error("Batch HTTP %d: %s", resp.status_code, resp.text[:300])
            return 0, len(records)
        except requests.RequestException as exc:
            log.warning("Batch request error (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    return 0, len(records)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------
def load_column_types(table_logical_name: str) -> dict[str, str]:
    """Load {logical_name: access_type} mapping from Dataverse schema JSON."""
    schema_file = os.path.join(SCHEMA_DIR, f"{table_logical_name}.json")
    # Fall back to raw Access table name matching
    if not os.path.isfile(schema_file):
        # Try to find by access_source_table
        for fname in os.listdir(SCHEMA_DIR):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(SCHEMA_DIR, fname)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("access_source_table", "").lower() == table_logical_name.lower():
                schema_file = path
                break
        else:
            return {}
    with open(schema_file, encoding="utf-8") as f:
        data = json.load(f)

    col_types = {}
    # Primary column
    pa = data.get("PrimaryAttribute", {})
    if pa.get("LogicalName"):
        col_types[pa["LogicalName"]] = "Text"

    for col in data.get("Columns", []):
        col_types[col["LogicalName"]] = col.get("access_source_type", "Text")

    return col_types


def map_csv_row_to_record(row: dict, csv_headers: list[str],
                          dv_schema: dict, col_types: dict) -> dict:
    """Convert a CSV row dict to a Dataverse record dict."""
    record = {}
    columns = dv_schema.get("Columns", [])
    pa = dv_schema.get("PrimaryAttribute", {})

    # Build source→logical mapping
    col_map = {}  # access_col_name → {logical, type}
    if pa.get("access_source_column"):
        col_map[pa["access_source_column"]] = {
            "logical": pa["LogicalName"],
            "type": "Text",
        }
    elif pa.get("LogicalName"):
        # Infer from display name
        pass

    for col in columns:
        src = col.get("access_source_column")
        if src:
            col_map[src] = {
                "logical": col["LogicalName"],
                "type": col.get("access_source_type", "Text"),
            }

    for header in csv_headers:
        val = row.get(header, "")
        if header in col_map:
            info = col_map[header]
            coerced = coerce_value(val, info["type"])
            if coerced is not None:
                record[info["logical"]] = coerced

    return record


# ---------------------------------------------------------------------------
# Main migration
# ---------------------------------------------------------------------------
def pluralise(name: str) -> str:
    """
    Return a basic plural form of an entity logical name.
    Dataverse default plural names follow English rules; override here if needed.
    Common endings handled: -y → -ies, -s/-x/-z/-ch/-sh → -es, else +s.
    """
    if name.endswith("y") and not name[-2] in "aeiou":
        return name[:-1] + "ies"
    if name[-1] in "sxz" or name.endswith("ch") or name.endswith("sh"):
        return name + "es"
    return name + "s"


def migrate_table(session: requests.Session, base_url: str,
                  csv_path: str, dv_schema: dict, dry_run: bool) -> tuple[int, int]:
    """Migrate all rows from a CSV file into the corresponding Dataverse table."""
    entity_set = pluralise(dv_schema["LogicalName"])
    table_name = dv_schema.get("access_source_table", "Unknown")

    log.info("Migrating table: %s → %s", table_name, entity_set)
    total_success = 0
    total_fail = 0
    batch = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        col_types = load_column_types(dv_schema["LogicalName"])

        for row in reader:
            record = map_csv_row_to_record(row, headers, dv_schema, col_types)
            if record:
                batch.append(record)

            if len(batch) >= BATCH_SIZE:
                s, e = send_batch(session, base_url, entity_set, batch, dry_run)
                total_success += s
                total_fail += e
                log.info("  Batch sent: %d ok, %d failed (running: %d ok / %d fail)",
                         s, e, total_success, total_fail)
                batch = []

    if batch:
        s, e = send_batch(session, base_url, entity_set, batch, dry_run)
        total_success += s
        total_fail += e

    log.info("Table %s done: %d inserted, %d failed", table_name, total_success, total_fail)
    return total_success, total_fail


def main():
    parser = argparse.ArgumentParser(description="Migrate Access CSV data to Dataverse")
    parser.add_argument("--table", help="Migrate only this table (Access source name)")
    parser.add_argument("--dry-run", action="store_true", help="Validate without inserting")
    parser.add_argument("--url", default=os.environ.get("DATAVERSE_URL"), help="Dataverse org URL")
    args = parser.parse_args()

    dataverse_url = (args.url or "").rstrip("/")
    if not dataverse_url:
        log.error("DATAVERSE_URL not set. Use --url or set env var DATAVERSE_URL.")
        sys.exit(1)

    token = get_access_token(dataverse_url)

    session = requests.Session()
    session.headers.update(get_headers(token))

    # Load all Dataverse table schema files
    if not os.path.isdir(SCHEMA_DIR):
        log.error("Dataverse schema dir not found: %s", SCHEMA_DIR)
        sys.exit(1)

    schema_files = [f for f in os.listdir(SCHEMA_DIR) if f.endswith(".json")]
    schema_map = {}  # access_source_table → schema dict
    for fname in schema_files:
        with open(os.path.join(SCHEMA_DIR, fname), encoding="utf-8") as f:
            dv_schema = json.load(f)
        src_table = dv_schema.get("access_source_table")
        if src_table:
            schema_map[src_table] = dv_schema

    # Load CSV files
    csv_files = list(Path(TABLES_DIR).glob("*.csv"))
    if not csv_files:
        log.error("No CSV files found in %s", TABLES_DIR)
        sys.exit(1)

    total_ok = 0
    total_err = 0

    for csv_path in sorted(csv_files):
        table_name = csv_path.stem
        if args.table and table_name.lower() != args.table.lower():
            continue

        dv_schema = schema_map.get(table_name)
        if not dv_schema:
            log.warning("No Dataverse schema for table '%s' — skipping", table_name)
            continue

        ok, err = migrate_table(session, dataverse_url, str(csv_path), dv_schema, args.dry_run)
        total_ok += ok
        total_err += err

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"\n✅ {prefix}Migration complete: {total_ok} inserted, {total_err} failed.")


if __name__ == "__main__":
    main()
