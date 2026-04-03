"""
generate_dataverse_schema.py
-----------------------------
Step 2 — Dataverse Schema Generation

Reads the extracted schema JSON files from /data/schema/ and produces:
  - /dataverse/tables/<table>.json   — Dataverse table/column definitions
  - /dataverse/relationships.json    — 1:N relationship definitions
  - /dataverse/solution_components.json — component manifest for the solution

Access type → Dataverse type mapping:
  Text        → String          (SingleLine.Text)
  Memo        → Memo            (Multiple.Text)
  Boolean     → Boolean
  Integer/Long/Byte/BigInt → Integer
  Single/Double/Decimal → Decimal
  DateTime    → DateTime
  Currency    → Money
  Guid        → Uniqueidentifier
  LongBinary  → (skipped — OLE Object not supported)

Usage:
  python generate_dataverse_schema.py
"""

import json
import logging
import os
import re
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("generate_dataverse_schema.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCHEMA_DIR = "../data/schema"
DATAVERSE_DIR = "../dataverse/tables"
PREFIX = "auto_"           # logical name prefix
PUBLISHER_PREFIX = "auto"  # must match your Dataverse publisher prefix
SOLUTION_NAME = "AccessMigration"

# Dataverse String column constraints
STRING_DEFAULT_MAX_LENGTH = 255    # default when Access column_size is None
STRING_ABSOLUTE_MAX_LENGTH = 4000  # Dataverse max for Single Line Text

# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------
ACCESS_TO_DATAVERSE = {
    "Text":       {"type": "String",   "format": "Text",           "dv_type": "Microsoft.Dynamics.CRM.StringAttributeMetadata"},
    "Memo":       {"type": "Memo",     "format": "TextArea",       "dv_type": "Microsoft.Dynamics.CRM.MemoAttributeMetadata"},
    "Boolean":    {"type": "Boolean",                              "dv_type": "Microsoft.Dynamics.CRM.BooleanAttributeMetadata"},
    "Integer":    {"type": "Integer",                              "dv_type": "Microsoft.Dynamics.CRM.IntegerAttributeMetadata"},
    "Long":       {"type": "Integer",                              "dv_type": "Microsoft.Dynamics.CRM.IntegerAttributeMetadata"},
    "Byte":       {"type": "Integer",                              "dv_type": "Microsoft.Dynamics.CRM.IntegerAttributeMetadata"},
    "BigInt":     {"type": "BigInt",                               "dv_type": "Microsoft.Dynamics.CRM.BigIntAttributeMetadata"},
    "Single":     {"type": "Double",                               "dv_type": "Microsoft.Dynamics.CRM.DoubleAttributeMetadata"},
    "Double":     {"type": "Double",                               "dv_type": "Microsoft.Dynamics.CRM.DoubleAttributeMetadata"},
    "Decimal":    {"type": "Decimal",                              "dv_type": "Microsoft.Dynamics.CRM.DecimalAttributeMetadata"},
    "Currency":   {"type": "Money",                                "dv_type": "Microsoft.Dynamics.CRM.MoneyAttributeMetadata"},
    "DateTime":   {"type": "DateTime", "format": "DateAndTime",    "dv_type": "Microsoft.Dynamics.CRM.DateTimeAttributeMetadata"},
    "Guid":       {"type": "Uniqueidentifier",                     "dv_type": "Microsoft.Dynamics.CRM.UniqueIdentifierAttributeMetadata"},
    "LongBinary": None,   # OLE Object — skip
    "Binary":     None,   # skip
    "Attachment": None,   # skip
}

SKIP_TYPES = {k for k, v in ACCESS_TO_DATAVERSE.items() if v is None}


def to_logical_name(name: str) -> str:
    """Convert a table/column name to a Dataverse-safe logical name."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return f"{PREFIX}{name}"


def to_display_name(name: str) -> str:
    """Human-readable display name."""
    return name.replace("_", " ").title()


def build_column_metadata(col: dict) -> dict | None:
    """Build a Dataverse column metadata dict from an Access column dict."""
    access_type = col.get("type", "Text")
    dv_info = ACCESS_TO_DATAVERSE.get(access_type)

    if dv_info is None:
        log.debug("Skipping column '%s' (type %s not supported in Dataverse)", col["name"], access_type)
        return None

    logical_name = to_logical_name(col["name"])
    display_name = to_display_name(col["name"])

    meta = {
        "@odata.type": dv_info["dv_type"],
        "SchemaName": logical_name,
        "LogicalName": logical_name,
        "DisplayName": {
            "@odata.type": "Microsoft.Dynamics.CRM.Label",
            "LocalizedLabels": [{"@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel", "Label": display_name, "LanguageCode": 1033}],
        },
        "RequiredLevel": {"Value": "None" if col.get("nullable", True) else "ApplicationRequired"},
        "IsValidForCreate": True,
        "IsValidForUpdate": True,
        "access_source_column": col["name"],
        "access_source_type": access_type,
    }

    dv_type = dv_info["type"]

    if dv_type == "String":
        meta["MaxLength"] = min(col.get("max_length") or STRING_DEFAULT_MAX_LENGTH, STRING_ABSOLUTE_MAX_LENGTH)
        meta["Format"] = dv_info.get("format", "Text")
    elif dv_type == "Memo":
        meta["Format"] = "TextArea"
        meta["MaxLength"] = 1048576
    elif dv_type == "Integer":
        meta["MinValue"] = -2147483648
        meta["MaxValue"] = 2147483647
    elif dv_type == "Double":
        meta["Precision"] = 5
    elif dv_type == "Decimal":
        meta["Precision"] = 10
        meta["MinValue"] = -100000000000
        meta["MaxValue"] = 100000000000
    elif dv_type == "Money":
        meta["Precision"] = 4
        meta["MinValue"] = -922337203685477.0
        meta["MaxValue"] = 922337203685477.0
    elif dv_type == "DateTime":
        meta["Format"] = dv_info.get("format", "DateAndTime")
        meta["DateTimeBehavior"] = {"Value": "UserLocal"}

    return meta


def build_table_definition(table_schema: dict) -> dict:
    """Build full Dataverse table definition from Access table schema."""
    table_name = table_schema["table_name"]
    logical_name = to_logical_name(table_name)
    schema_name = logical_name
    primary_keys = table_schema.get("primary_keys", [])

    # Determine a suitable primary column (first text PK, or first text col)
    primary_col_name = None
    for pk in primary_keys:
        col = next((c for c in table_schema["columns"] if c["name"] == pk), None)
        if col and col["type"] == "Text":
            primary_col_name = col["name"]
            break
    if not primary_col_name:
        text_cols = [c for c in table_schema["columns"] if c["type"] == "Text"]
        primary_col_name = text_cols[0]["name"] if text_cols else None

    primary_column_logical_name = to_logical_name(primary_col_name) if primary_col_name else f"{logical_name}name"

    # Build column list (skip unsupported types and the PK if it becomes the primary column)
    columns = []
    for col in table_schema["columns"]:
        col_logical = to_logical_name(col["name"])
        # Skip the primary display column (handled as EntityPrimaryAttribute)
        if primary_col_name and col["name"] == primary_col_name:
            continue
        meta = build_column_metadata(col)
        if meta:
            # Mark if this is a primary key source
            meta["is_primary_key_source"] = col["name"] in primary_keys
            columns.append(meta)

    table_def = {
        "@odata.type": "Microsoft.Dynamics.CRM.EntityMetadata",
        "SchemaName": schema_name,
        "LogicalName": logical_name,
        "DisplayName": {
            "@odata.type": "Microsoft.Dynamics.CRM.Label",
            "LocalizedLabels": [{"@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel", "Label": to_display_name(table_name), "LanguageCode": 1033}],
        },
        "DisplayCollectionName": {
            "@odata.type": "Microsoft.Dynamics.CRM.Label",
            "LocalizedLabels": [{"@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel", "Label": to_display_name(table_name) + "s", "LanguageCode": 1033}],
        },
        "Description": {
            "@odata.type": "Microsoft.Dynamics.CRM.Label",
            "LocalizedLabels": [{"@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel", "Label": f"Migrated from Access table: {table_name}", "LanguageCode": 1033}],
        },
        "OwnershipType": "UserOwned",
        "HasActivities": False,
        "HasNotes": False,
        "IsActivity": False,
        "IsAuditEnabled": {"Value": False},
        "PrimaryNameAttribute": primary_column_logical_name,
        "PrimaryAttribute": {
            "@odata.type": "Microsoft.Dynamics.CRM.StringAttributeMetadata",
            "SchemaName": primary_column_logical_name,
            "LogicalName": primary_column_logical_name,
            "DisplayName": {
                "@odata.type": "Microsoft.Dynamics.CRM.Label",
                "LocalizedLabels": [{"@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel",
                                     "Label": to_display_name(primary_col_name) if primary_col_name else "Name",
                                     "LanguageCode": 1033}],
            },
            "RequiredLevel": {"Value": "ApplicationRequired"},
            "MaxLength": 255,
        },
        "Columns": columns,
        "access_source_table": table_name,
        "access_primary_keys": primary_keys,
    }
    return table_def


def build_relationships(relationships: list[dict]) -> list[dict]:
    """Build Dataverse 1:N relationship definitions."""
    dv_rels = []
    for rel in relationships:
        pk_table_logical = to_logical_name(rel["pk_table"])
        fk_table_logical = to_logical_name(rel["fk_table"])
        pk_col_logical = to_logical_name(rel["pk_column"])
        fk_col_logical = to_logical_name(rel["fk_column"])
        schema_name = f"{pk_table_logical}_{fk_table_logical}_{fk_col_logical}"

        dv_rel = {
            "@odata.type": "Microsoft.Dynamics.CRM.OneToManyRelationshipMetadata",
            "SchemaName": schema_name,
            "ReferencedEntity": pk_table_logical,
            "ReferencedAttribute": pk_col_logical,
            "ReferencingEntity": fk_table_logical,
            "ReferencingAttribute": fk_col_logical,
            "CascadeConfiguration": {
                "@odata.type": "Microsoft.Dynamics.CRM.CascadeConfiguration",
                "Assign": "NoCascade",
                "Delete": "RemoveLink",
                "Merge": "NoCascade",
                "Reparent": "NoCascade",
                "Share": "NoCascade",
                "Unshare": "NoCascade",
            },
            "access_source": rel,
        }
        dv_rels.append(dv_rel)
    return dv_rels


def main():
    os.makedirs(DATAVERSE_DIR, exist_ok=True)

    # Load all per-table schema files
    if not os.path.isdir(SCHEMA_DIR):
        log.error("Schema directory not found: %s — run extract_access.py first.", SCHEMA_DIR)
        sys.exit(1)

    table_files = [f for f in os.listdir(SCHEMA_DIR) if f.endswith(".json") and not f.startswith("_")]
    if not table_files:
        log.error("No table schema files found in %s", SCHEMA_DIR)
        sys.exit(1)

    solution_components = []

    for fname in sorted(table_files):
        path = os.path.join(SCHEMA_DIR, fname)
        with open(path, encoding="utf-8") as f:
            table_schema = json.load(f)

        table_def = build_table_definition(table_schema)
        out_path = os.path.join(DATAVERSE_DIR, fname)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(table_def, f, indent=2)
        log.info("Dataverse table definition written: %s", out_path)

        solution_components.append({
            "type": "Entity",
            "schemaName": table_def["SchemaName"],
            "logicalName": table_def["LogicalName"],
        })

    # Load and convert relationships
    rel_path = os.path.join(SCHEMA_DIR, "_relationships.json")
    if os.path.isfile(rel_path):
        with open(rel_path, encoding="utf-8") as f:
            relationships = json.load(f)
        dv_rels = build_relationships(relationships)
        out_rel_path = os.path.join(os.path.dirname(DATAVERSE_DIR), "relationships.json")
        with open(out_rel_path, "w", encoding="utf-8") as f:
            json.dump(dv_rels, f, indent=2)
        log.info("Relationships written: %s", out_rel_path)
        for r in dv_rels:
            solution_components.append({
                "type": "Relationship",
                "schemaName": r["SchemaName"],
            })

    # Write solution component manifest
    manifest = {
        "solution_name": SOLUTION_NAME,
        "publisher_prefix": PUBLISHER_PREFIX,
        "components": solution_components,
    }
    manifest_path = os.path.join(os.path.dirname(DATAVERSE_DIR), "solution_components.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    log.info("Solution manifest written: %s", manifest_path)

    print("\n✅ Dataverse schema generation complete.")
    print(f"   Table definitions → {os.path.abspath(DATAVERSE_DIR)}")
    print(f"   Manifest          → {os.path.abspath(manifest_path)}")


if __name__ == "__main__":
    main()
