# Access Power Booster

Converts a Microsoft Access (`.accdb`) database into **Microsoft Dataverse tables** and deploys a working **Canvas Power App** on top — fully automated, end-to-end.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Linux or Windows** | Tested in GitHub Codespaces (Ubuntu) |
| **Python 3.9+** | `python --version` |
| **mdbtools** | `sudo apt-get install mdbtools` — reads `.accdb`/`.mdb` files on Linux |
| **Power Platform CLI (`pac`)** | [Install guide](https://aka.ms/PowerAppsCLI) |
| **Azure CLI (`az`)** | Optional — used as token fallback |
| **Power Platform environment** | With Dataverse enabled |
| **Azure AD App Registration** | With `Dynamics CRM → user_impersonation` permission |

---

## Project Structure

```
/
├── input/
│   └── Database3.accdb         ← Your Access database (place it here)
├── scripts/
│   ├── extract_access_linux.py ← Step 1: Extract schema + data from Access (mdbtools)
│   ├── extract_access.py       ← Step 1: (Windows-only alternative, requires OLEDB)
│   ├── generate_dataverse_schema.py  ← Step 2: Map to Dataverse types
│   ├── migrate_data.py         ← Step 4: Load CSV data into Dataverse
│   ├── generate_powerapp.py    ← Step 5: Generate Canvas App source
│   ├── auth.sh                ← Step 3a: pac authentication
│   ├── create-solution.sh     ← Step 3b: Create Dataverse solution + tables
│   └── import-solution.sh     ← Step 3c: Pack + import Canvas App
├── dataverse/
│   ├── tables/                 ← Generated Dataverse table JSON definitions
│   └── relationships.json      ← Detected FK relationships
├── data/
│   ├── schema/                 ← Per-table schema JSON (from Access)
│   └── tables/                 ← Per-table CSV exports
├── powerapp/
│   └── src/                    ← Unpacked Canvas App source (Power Fx YAML)
│       ├── App.fx.yaml
│       ├── CanvasManifest.json
│       └── Screens/
│           ├── <Table>BrowseScreen.fx.yaml
│           ├── <Table>DetailScreen.fx.yaml
│           └── <Table>EditScreen.fx.yaml
├── run-all.sh                  ← Master orchestration script
├── .env.example                ← Environment variable template
└── README.md
```

---

## Setup

### 1. Clone and configure

```bash
# Copy environment template
cp .env.example .env
# Edit .env with your values
nano .env
```

Fill in `.env`:

```
DATAVERSE_URL=https://yourorg.crm.dynamics.com
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=your-client-secret-here
```

### 2. Install dependencies

```bash
sudo apt-get install mdbtools
pip install requests msal
```

### 3. Place your Access database

```
input/Database3.accdb
```

---

## Running the Full Pipeline

### All-in-one (recommended)

```bash
./run-all.sh
```

### Skip flags

```bash
# Skip extraction if data/schema/ and data/tables/ already exist
./run-all.sh --skip-extract

# Validate data migration without inserting records
./run-all.sh --dry-run

# Skip Power App generation and import
./run-all.sh --skip-app
```

---

## Running Steps Individually

### Step 1 — Extract Access DB

```bash
cd scripts
python extract_access_linux.py --db ../input/Database3.accdb
```

Outputs:
- `data/schema/<table>.json` — column types, primary keys
- `data/schema/_relationships.json` — detected FK relationships
- `data/tables/<table>.csv` — all table data

### Step 2 — Generate Dataverse Schema

```bash
python generate_dataverse_schema.py
```

Outputs:
- `dataverse/tables/<table>.json` — Dataverse table/column metadata
- `dataverse/relationships.json` — 1:N relationship definitions
- `dataverse/solution_components.json` — solution manifest

### Step 3 — Deploy Dataverse Schema

```bash
# Authenticate
./scripts/auth.sh

# Create solution + tables + relationships
./scripts/create-solution.sh
```

### Step 4 — Migrate Data

```bash
python scripts/migrate_data.py
# or dry-run:
python scripts/migrate_data.py --dry-run
# or single table:
python scripts/migrate_data.py --table Customers
```

### Step 5 — Generate Power App

```bash
python scripts/generate_powerapp.py
```

Outputs screen files to `powerapp/src/Screens/`.

### Step 6 — Import App + Solution

```bash
./scripts/import-solution.sh
```

---

## After Deployment

1. Open [Power Apps Studio](https://make.powerapps.com)
2. Navigate to **Solutions → AccessMigration**
3. Open the **AccessMigratedApp** Canvas App
4. Add Dataverse table connections via the **Data** panel
5. Test Browse → Detail → Edit screens for each table

---

## Type Mapping Reference

| Access Type | Dataverse Type |
|---|---|
| Text | Single Line Text (String) |
| Memo / Long Text | Multiline Text (Memo) |
| Yes/No | Two Option (Boolean) |
| Number (Integer/Long) | Whole Number (Integer) |
| Number (Single/Double) | Floating Point (Double) |
| Number (Decimal) | Decimal Number |
| Currency | Currency (Money) |
| Date/Time | Date and Time |
| AutoNumber / GUID | Unique Identifier |
| OLE Object / Binary | ❌ Skipped (not supported) |

---

## Known Limitations

- **mdbtools** is used for extraction — some edge-case type detection may differ from the Windows OLEDB driver.
- **OLE Object columns** are skipped (binary blobs are not supported in Dataverse via Web API).
- **Complex relationships** (many-to-many) are not auto-detected — add manually in Power Apps Studio.
- **Attachment columns** are not migrated.
- **Large databases** (>5 MB of data) may take several minutes due to Dataverse API rate limits.
- The generated Canvas App uses **logical column names** — you may want to update display names in Studio.
- Access AutoNumber PKs become Integer fields; Dataverse uses its own GUID primary keys internally.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `mdb-tables: command not found` | Install mdbtools: `sudo apt-get install mdbtools` |
| `pac: command not found` | Install [Power Platform CLI](https://aka.ms/PowerAppsCLI) and restart terminal |
| `401 Unauthorized` on Dataverse API | Check `AZURE_CLIENT_ID`/`SECRET`/`TENANT_ID` in `.env` |
| `pac canvas pack` fails | Ensure pac CLI version ≥ 1.27; run `pac install latest` |
| Tables not appearing in Power Apps | Refresh the browser; check Solution → Tables |
