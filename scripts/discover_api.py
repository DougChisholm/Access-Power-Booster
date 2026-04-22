"""Discover the correct Dataverse API structure for sitemaps and app modules."""
import msal, os, requests, json, sys

app = msal.ConfidentialClientApplication(os.environ['AZURE_CLIENT_ID'],
    authority='https://login.microsoftonline.com/' + os.environ['AZURE_TENANT_ID'],
    client_credential=os.environ['AZURE_CLIENT_SECRET'])
t = app.acquire_token_for_client(scopes=[os.environ['DATAVERSE_URL'] + '/.default'])['access_token']
base = os.environ['DATAVERSE_URL'].rstrip('/') + '/api/data/v9.2'
h = {'Authorization': 'Bearer ' + t, 'OData-Version': '4.0', 'Accept': 'application/json'}

app_id = "5d92e977-5087-4f4c-b81d-5837e7ccfe44"

# 1. All properties of our app module
print("=== APP MODULE RECORD ===")
r = requests.get(f'{base}/appmodules({app_id})', headers=h)
if r.status_code == 200:
    data = r.json()
    for k, v in sorted(data.items()):
        if not k.startswith('@odata'):
            print(f"  {k}: {repr(v)[:120]}")
else:
    print(f"  Error: {r.status_code} {r.text[:200]}")

# 2. Appmodule 1-to-many relationships (find sitemap link)
print("\n=== APPMODULE ONE-TO-MANY RELATIONSHIPS ===")
r = requests.get(f'{base}/EntityDefinitions(LogicalName=\'appmodule\')/OneToManyRelationships?$select=SchemaName,ReferencingEntity,ReferencingAttribute', headers=h)
if r.status_code == 200:
    for rel in r.json().get('value', []):
        e = rel.get('ReferencingEntity', '')
        if 'site' in e.lower() or 'component' in e.lower() or 'app' in e.lower():
            print(f"  {rel['SchemaName']}: {e}.{rel.get('ReferencingAttribute')}")

# 3. Appmodule many-to-one relationships
print("\n=== APPMODULE MANY-TO-ONE RELATIONSHIPS ===")
r = requests.get(f'{base}/EntityDefinitions(LogicalName=\'appmodule\')/ManyToOneRelationships?$select=SchemaName,ReferencedEntity,ReferencingAttribute', headers=h)
if r.status_code == 200:
    for rel in r.json().get('value', []):
        print(f"  {rel['SchemaName']}: -> {rel.get('ReferencedEntity')}.{rel.get('ReferencingAttribute')}")

# 4. Find sitemap-related entities
print("\n=== SITEMAP-RELATED ENTITIES ===")
r = requests.get(f"{base}/EntityDefinitions?$filter=contains(LogicalName,'sitemap')&$select=LogicalName,EntitySetName", headers=h)
if r.status_code == 200:
    for e in r.json().get('value', []):
        print(f"  {e['LogicalName']} (set: {e.get('EntitySetName')})")
        # Get its attributes
        r2 = requests.get(f"{base}/EntityDefinitions(LogicalName='{e['LogicalName']}')/Attributes?$select=LogicalName,AttributeType", headers=h)
        if r2.status_code == 200:
            for a in r2.json().get('value', []):
                print(f"    {a['LogicalName']}: {a.get('AttributeType')}")

# 5. Existing sitemaps
print("\n=== EXISTING SITEMAPS ===")
r = requests.get(f'{base}/sitemaps?$top=3', headers=h)
if r.status_code == 200:
    for s in r.json().get('value', []):
        print(json.dumps(s, indent=2)[:500])
else:
    print(f"  {r.status_code} {r.text[:200]}")
