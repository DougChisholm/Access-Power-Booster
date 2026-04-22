"""
create_model_app.py
-------------------
Creates a Model-Driven App in Dataverse for all migrated tables.

Uses the Dataverse Web API to:
  1. Create an AppModule
  2. Collect forms + views for each entity
  3. Create a SiteMap record
  4. Add forms, views, and sitemap via AddAppComponents
     (Components param expects actual entity records like systemform/savedquery/sitemap,
      NOT appmodulecomponent records — entities are included automatically)
  5. Publish the app

Usage:
  python create_model_app.py --url https://org.crm.dynamics.com --solution AccessMigration
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import uuid

try:
    import msal
    import requests
except ImportError:
    print("ERROR: Install dependencies: pip install msal requests")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def get_token(dataverse_url: str) -> str:
    """Acquire OAuth2 token using MSAL client credentials."""
    tenant_id = os.environ.get("AZURE_TENANT_ID", "")
    client_id = os.environ.get("AZURE_CLIENT_ID", "")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET", "")

    if not all([tenant_id, client_id, client_secret]):
        log.error("Missing AZURE_TENANT_ID, AZURE_CLIENT_ID, or AZURE_CLIENT_SECRET")
        sys.exit(1)

    app = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )
    result = app.acquire_token_for_client(scopes=[f"{dataverse_url}/.default"])
    if "access_token" not in result:
        log.error("Token acquisition failed: %s", result.get("error_description"))
        sys.exit(1)
    return result["access_token"]


def api(session: requests.Session, method: str, url: str, json_body=None):
    """Make a Dataverse API call and return the response."""
    resp = session.request(method, url, json=json_body)
    if resp.status_code >= 400:
        log.error("API %s %s → %s: %s", method, url.split("/api/")[-1], resp.status_code, resp.text[:500])
    return resp


def main():
    parser = argparse.ArgumentParser(description="Create Model-Driven App")
    parser.add_argument("--url", required=True, help="Dataverse URL")
    parser.add_argument("--solution", default="AccessMigration")
    parser.add_argument("--app-name", default="AccessMigratedModelApp")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    api_base = f"{base}/api/data/v9.2"
    token = get_token(base)

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "MSCRM.SolutionName": args.solution,
    })

    # ── 1. Get all auto_ tables ──────────────────────────────────────────────

    log.info("Fetching auto_ tables...")
    resp = api(session, "GET",
               f"{api_base}/EntityDefinitions?$select=LogicalName,MetadataId,DisplayName"
               "&$filter=IsCustomEntity eq true")
    if resp.status_code != 200:
        log.error("Could not fetch entity definitions.")
        sys.exit(1)

    entities = [e for e in resp.json().get("value", [])
                if e["LogicalName"].startswith("auto_")]
    if not entities:
        log.error("No auto_ tables found. Run create-solution.sh first.")
        sys.exit(1)
    log.info("Found %d tables: %s", len(entities),
             [e["LogicalName"] for e in entities])

    # ── 2. Collect forms and views for each entity ───────────────────────────

    all_components = []

    for entity in entities:
        name = entity["LogicalName"]
        log.info("  Collecting forms/views for: %s", name)

        # All forms for this entity
        r = api(session, "GET",
                f"{api_base}/systemforms?$filter=objecttypecode eq '{name}'"
                f"&$select=formid,name,type")
        if r.status_code == 200:
            for form in r.json().get("value", []):
                all_components.append({
                    "@odata.type": "#Microsoft.Dynamics.CRM.systemform",
                    "formid": form["formid"],
                })
                log.info("    Form: %s (type=%s)", form.get("name"), form.get("type"))

        # All views for this entity
        r = api(session, "GET",
                f"{api_base}/savedqueries?$filter=returnedtypecode eq '{name}'"
                f"&$select=savedqueryid,name,querytype")
        if r.status_code == 200:
            for view in r.json().get("value", []):
                all_components.append({
                    "@odata.type": "#Microsoft.Dynamics.CRM.savedquery",
                    "savedqueryid": view["savedqueryid"],
                })
                log.info("    View: %s", view.get("name"))

    log.info("Collected %d form/view components total.", len(all_components))

    # ── 3. Create the AppModule ──────────────────────────────────────────────

    resp = api(session, "GET",
               f"{api_base}/appmodules?$select=appmoduleid,uniquename,name")
    all_apps = resp.json().get("value", []) if resp.status_code == 200 else []
    existing = [a for a in all_apps
                if "AccessMigrated" in a.get("uniquename", "")
                or a.get("name") == "Access Migrated App"]

    if existing:
        app_id = existing[0]["appmoduleid"]
        log.info("Reusing app: %s (%s)", existing[0].get("uniquename"), app_id)
    else:
        log.info("Creating app module...")

        # Find web resource for icon
        wr_resp = api(session, "GET",
                      f"{api_base}/webresourceset?$filter=webresourcetype eq 5"
                      "&$top=1&$select=webresourceid")
        wr_values = wr_resp.json().get("value", []) if wr_resp.status_code == 200 else []
        if not wr_values:
            png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPj/HwADBwIAMCbHYQAAAABJRU5ErkJggg=="
            api(session, "POST", f"{api_base}/webresourceset", {
                "name": "auto_/Images/AppIcon.png", "displayname": "App Icon",
                "webresourcetype": 5, "content": png_b64})
            wr_resp = api(session, "GET",
                          f"{api_base}/webresourceset?$filter=name eq 'auto_/Images/AppIcon.png'"
                          "&$select=webresourceid")
            wr_values = wr_resp.json().get("value", []) if wr_resp.status_code == 200 else []
        if not wr_values:
            log.error("No web resource for icon.")
            sys.exit(1)
        wr_id = wr_values[0]["webresourceid"]

        short_hash = hashlib.md5(uuid.uuid4().bytes).hexdigest()[:6]
        unique_name = f"{args.app_name}_{short_hash}"

        app_payload = {
            "uniquename": unique_name,
            "name": "Access Migrated App",
            "description": "Model-driven app from Access DB migration",
            "clienttype": 4,
            "navigationtype": 0,
            "webresourceid": wr_id,
        }
        resp = api(session, "POST", f"{api_base}/appmodules", app_payload)
        if resp.status_code >= 400:
            log.error("Failed to create app module.")
            sys.exit(1)
        if resp.status_code == 204:
            eid = resp.headers.get("OData-EntityId", "")
            app_id = eid.split("(")[-1].rstrip(")") if "(" in eid else ""
        else:
            app_id = resp.json().get("appmoduleid", "")
        if not app_id:
            log.error("Could not extract app ID.")
            sys.exit(1)
        log.info("App created: %s (uniquename=%s)", app_id, unique_name)

    # ── 4. Create SiteMap ────────────────────────────────────────────────────

    log.info("Creating sitemap...")
    subareas = ""
    for entity in entities:
        name = entity["LogicalName"]
        labels = entity.get("DisplayName", {}).get("LocalizedLabels", [{}])
        display = labels[0].get("Label", name) if labels else name
        subareas += (
            f'<SubArea Id="sub_{name}" Entity="{name}">'
            f'<Titles><Title LCID="1033" Title="{display}" /></Titles>'
            f'</SubArea>')

    sitemap_xml = (
        '<SiteMap>'
        '<Area Id="MainArea" Title="Tables">'
        '<Group Id="MainGroup" Title="Migrated Tables">'
        f'{subareas}'
        '</Group></Area></SiteMap>')

    sm_id = str(uuid.uuid4())
    r = api(session, "POST", f"{api_base}/sitemaps", {
        "sitemapid": sm_id,
        "sitemapnameunique": f"auto_sitemap_{sm_id[:8]}",
        "sitemapname": "Access Migrated App SiteMap",
        "sitemapxml": sitemap_xml,
        "isappaware": True,
    })
    if r.status_code < 400:
        if r.status_code == 204:
            eid = r.headers.get("OData-EntityId", "")
            if "(" in eid:
                sm_id = eid.split("(")[-1].rstrip(")")
        elif r.status_code in (200, 201):
            sm_id = r.json().get("sitemapid", sm_id)
        log.info("Sitemap created: %s", sm_id)
        all_components.append({
            "@odata.type": "#Microsoft.Dynamics.CRM.sitemap",
            "sitemapid": sm_id,
        })
    else:
        log.warning("Sitemap creation failed: %s", r.text[:300])

    # ── 5. Add all components via AddAppComponents ───────────────────────────

    log.info("Adding %d components to app...", len(all_components))

    # Add in batches
    batch_size = 20
    added = 0
    for i in range(0, len(all_components), batch_size):
        batch = all_components[i:i + batch_size]
        r = api(session, "POST", f"{api_base}/AddAppComponents",
                {"AppId": app_id, "Components": batch})
        if r.status_code < 400:
            added += len(batch)
            log.info("  Batch %d: %d components added.",
                     i // batch_size + 1, len(batch))
        else:
            log.warning("  Batch %d failed, trying one-by-one...",
                        i // batch_size + 1)
            for comp in batch:
                r2 = api(session, "POST", f"{api_base}/AddAppComponents",
                         {"AppId": app_id, "Components": [comp]})
                if r2.status_code < 400:
                    added += 1
                else:
                    ctype = comp.get("@odata.type", "?").split(".")[-1]
                    log.warning("    Failed %s: %s", ctype, r2.text[:200])

    log.info("Added %d/%d components.", added, len(all_components))

    # ── 6. Publish ───────────────────────────────────────────────────────────

    log.info("Publishing app...")
    resp = api(session, "POST", f"{api_base}/PublishAppModule",
               {"AppModuleId": app_id})
    if resp.status_code < 400:
        log.info("App published successfully!")
    else:
        log.warning("Publish failed: %s", resp.text[:500])
        log.info("Try: Power Apps → Solutions → %s → Edit app → Publish",
                 args.solution)

    log.info("Publishing all customizations...")
    api(session, "POST", f"{api_base}/PublishAllXml")

    app_url = f"{base}/main.aspx?appid={app_id}"
    log.info("")
    log.info("Done! App ID: %s", app_id)
    log.info("URL: %s", app_url)


if __name__ == "__main__":
    main()
