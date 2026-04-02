"""
generate_powerapp.py
--------------------
Step 5 — Canvas Power App Generation

Reads Dataverse table definitions from /dataverse/tables/ and generates
unpacked Canvas Power App source files in /powerapp/ ready for
`pac canvas pack` and `pac solution import`.

Output structure per table:
  /powerapp/
    App.msapp  (produced by pac canvas pack)
    src/
      App.fx.yaml
      Screens/
        <Table>BrowseScreen.fx.yaml
        <Table>DetailScreen.fx.yaml
        <Table>EditScreen.fx.yaml

Each screen includes:
  - Browse: Gallery with Search
  - Detail: Display Form
  - Edit/New: Edit Form with Save/Cancel/Delete

Usage:
  python generate_powerapp.py
"""

import json
import logging
import os
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("generate_powerapp.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

SCHEMA_DIR = "../dataverse/tables"
POWERAPP_DIR = "../powerapp/src"
PREFIX = "auto_"


def to_display_name(name: str) -> str:
    return name.replace(PREFIX, "").replace("_", " ").title()


def pascal(name: str) -> str:
    return to_display_name(name).replace(" ", "")


def get_string_columns(table: dict, limit: int = 5) -> list[str]:
    """Return logical names of the first N string-type columns."""
    string_types = {"String", "Memo"}
    cols = []
    # Always include primary name attribute first
    primary = table.get("PrimaryNameAttribute", "")
    if primary:
        cols.append(primary)
    for col in table.get("Columns", []):
        if col.get("access_source_type") in string_types and col["LogicalName"] not in cols:
            cols.append(col["LogicalName"])
        if len(cols) >= limit:
            break
    return cols


def generate_browse_screen(table_name: str, table: dict) -> str:
    display = to_display_name(table_name)
    pc = pascal(table_name)
    logical = table["LogicalName"]
    primary = table.get("PrimaryNameAttribute", f"{logical}name")
    string_cols = get_string_columns(table, 3)
    subtitle_col = string_cols[1] if len(string_cols) > 1 else primary

    return f"""\
# {pc} Browse Screen
As: Screen

BrowseGallery_{pc}:
  As: gallery.Vertical
  Items: =Filter({logical}, StartsWith({primary}, SearchInput_{pc}.Text))
  TemplateSize: =72

  Title_{pc}:
    As: label.Text
    Text: =ThisItem.{primary}

  Subtitle_{pc}:
    As: label.Text
    Text: =ThisItem.{subtitle_col}

  Arrow_{pc}:
    As: icon.ChevronRight
    OnSelect: =Navigate({pc}DetailScreen, ScreenTransition.Fade)

SearchInput_{pc}:
  As: input.text
  HintText: ="Search {display}..."
  Default: =""

BrowseHeader_{pc}:
  As: label.Text
  Text: ="{display}"
  FontWeight: =FontWeight.Bold

AddButton_{pc}:
  As: icon.Add
  OnSelect: =NewForm(EditForm_{pc}); Navigate({pc}EditScreen, ScreenTransition.Slide)
"""


def generate_detail_screen(table_name: str, table: dict) -> str:
    pc = pascal(table_name)
    logical = table["LogicalName"]
    primary = table.get("PrimaryNameAttribute", f"{logical}name")
    display = to_display_name(table_name)

    # Build display cards for all supported columns
    cards = []
    for col in [{"LogicalName": primary}] + table.get("Columns", []):
        col_logical = col["LogicalName"]
        col_display = to_display_name(col_logical)
        cards.append(f"""\
  DataCard_{pc}_{col_logical}:
    As: dataCard
    FieldDisplayName: ="{col_display}"
    DataField: ="{col_logical}"
""")

    cards_str = "\n".join(cards)

    return f"""\
# {pc} Detail Screen
As: Screen

DetailForm_{pc}:
  As: form.Display
  DataSource: ={logical}
  Item: =BrowseGallery_{pc}.Selected

{cards_str}

DetailHeader_{pc}:
  As: label.Text
  Text: ="{display} Detail"
  FontWeight: =FontWeight.Bold

BackButton_Detail_{pc}:
  As: icon.Back
  OnSelect: =Back()

EditButton_{pc}:
  As: icon.Edit
  OnSelect: =EditForm(EditForm_{pc}); Navigate({pc}EditScreen, ScreenTransition.Slide)

DeleteButton_{pc}:
  As: icon.Trash
  OnSelect: =Remove({logical}, BrowseGallery_{pc}.Selected); Back()
"""


def generate_edit_screen(table_name: str, table: dict) -> str:
    pc = pascal(table_name)
    logical = table["LogicalName"]
    primary = table.get("PrimaryNameAttribute", f"{logical}name")
    display = to_display_name(table_name)

    # Build edit cards
    cards = []
    # Primary attribute first
    cards.append(f"""\
  EditCard_{pc}_{primary}:
    As: dataCard
    FieldDisplayName: ="{to_display_name(primary)}"
    DataField: ="{primary}"
    Required: =true
""")
    for col in table.get("Columns", []):
        col_logical = col["LogicalName"]
        col_display = to_display_name(col_logical)
        required = col.get("RequiredLevel", {}).get("Value", "None") != "None"
        req_str = "true" if required else "false"
        cards.append(f"""\
  EditCard_{pc}_{col_logical}:
    As: dataCard
    FieldDisplayName: ="{col_display}"
    DataField: ="{col_logical}"
    Required: ={req_str}
""")

    cards_str = "\n".join(cards)

    return f"""\
# {pc} Edit/New Screen
As: Screen

EditForm_{pc}:
  As: form.Edit
  DataSource: ={logical}
  Item: =BrowseGallery_{pc}.Selected

{cards_str}

EditHeader_{pc}:
  As: label.Text
  Text: =If(EditForm_{pc}.Mode = FormMode.New, "New {display}", "Edit {display}")
  FontWeight: =FontWeight.Bold

SaveButton_{pc}:
  As: button.Button
  Text: ="Save"
  OnSelect: |=
    If(EditForm_{pc}.Valid,
      SubmitForm(EditForm_{pc});
      Navigate({pc}BrowseScreen, ScreenTransition.Back),
      Notify("Please fill in all required fields.", NotificationType.Warning)
    )

CancelButton_{pc}:
  As: button.Button
  Text: ="Cancel"
  OnSelect: =ResetForm(EditForm_{pc}); Back()
"""


def generate_app_fx(tables: list[dict]) -> str:
    """Generate App.fx.yaml with OnStart navigation setup."""
    first_table = tables[0] if tables else None
    first_screen = f"{pascal(first_table['LogicalName'])}BrowseScreen" if first_table else "Screen1"

    datasources = "\n".join(
        f"  - {t['LogicalName']}" for t in tables
    )

    return f"""\
# App definition
As: App

OnStart: =Navigate({first_screen}, ScreenTransition.None)

# Data sources (add these in Power Apps Studio → Data panel)
# DataSources:
{datasources}

# Screen order
Screens:
{chr(10).join(f"  - {pascal(t['LogicalName'])}BrowseScreen" + chr(10) + f"  - {pascal(t['LogicalName'])}DetailScreen" + chr(10) + f"  - {pascal(t['LogicalName'])}EditScreen" for t in tables)}
"""


def main():
    if not os.path.isdir(SCHEMA_DIR):
        log.error("Dataverse schema dir not found: %s — run generate_dataverse_schema.py first.", SCHEMA_DIR)
        sys.exit(1)

    schema_files = sorted(Path(SCHEMA_DIR).glob("*.json"))
    if not schema_files:
        log.error("No schema files in %s", SCHEMA_DIR)
        sys.exit(1)

    tables = []
    for sf in schema_files:
        with open(sf, encoding="utf-8") as f:
            tables.append(json.load(f))

    screens_dir = os.path.join(POWERAPP_DIR, "Screens")
    os.makedirs(screens_dir, exist_ok=True)

    for table in tables:
        table_logical = table["LogicalName"]
        pc = pascal(table_logical)

        browse = generate_browse_screen(table_logical, table)
        detail = generate_detail_screen(table_logical, table)
        edit   = generate_edit_screen(table_logical, table)

        for name, content in [
            (f"{pc}BrowseScreen.fx.yaml", browse),
            (f"{pc}DetailScreen.fx.yaml", detail),
            (f"{pc}EditScreen.fx.yaml",   edit),
        ]:
            out = os.path.join(screens_dir, name)
            with open(out, "w", encoding="utf-8") as f:
                f.write(content)
            log.info("Screen written: %s", out)

    # App.fx.yaml
    app_fx = generate_app_fx(tables)
    app_path = os.path.join(POWERAPP_DIR, "App.fx.yaml")
    with open(app_path, "w", encoding="utf-8") as f:
        f.write(app_fx)
    log.info("App definition written: %s", app_path)

    # CanvasManifest.json
    manifest = {
        "FormatVersion": 119,
        "SavedFromVersion": "3.23091",
        "Properties": {
            "DocumentType": "App",
            "Id": "com.access.migrated.app",
            "Name": "Access Migrated App",
            "Description": "Auto-generated from Access DB migration",
        },
        "PublishInfo": {"AppName": "AccessMigratedApp"},
    }
    manifest_path = os.path.join(POWERAPP_DIR, "CanvasManifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    log.info("Manifest written: %s", manifest_path)

    print(f"\n✅ Power App source files generated in: {os.path.abspath(POWERAPP_DIR)}")
    print("   Next steps:")
    print("   1. pac canvas pack --sources powerapp/src --msapp powerapp/App.msapp")
    print("   2. pac solution add-reference --path powerapp/App.msapp")
    print("   3. pac solution import")


if __name__ == "__main__":
    main()
