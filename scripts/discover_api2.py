"""Discover exact attribute names for appmodule and sitemap entities."""
import msal, os, requests, json

app = msal.ConfidentialClientApplication(os.environ['AZURE_CLIENT_ID'],
    authority='https://login.microsoftonline.com/' + os.environ['AZURE_TENANT_ID'],
    client_credential=os.environ['AZURE_CLIENT_SECRET'])
t = app.acquire_token_for_client(scopes=[os.environ['DATAVERSE_URL'] + '/.default'])['access_token']
base = os.environ['DATAVERSE_URL'].rstrip('/') + '/api/data/v9.2'
h = {'Authorization': 'Bearer ' + t, 'OData-Version': '4.0', 'Accept': 'application/json'}

# 1. ALL attributes of appmodule entity
print("=== APPMODULE ATTRIBUTES ===")
r = requests.get(f"{base}/EntityDefinitions(LogicalName='appmodule')/Attributes?$select=LogicalName,AttributeType", headers=h)
if r.status_code == 200:
    for a in sorted(r.json().get('value', []), key=lambda x: x['LogicalName']):
        print(f"  {a['LogicalName']}: {a.get('AttributeType')}")

# 2. ALL fields of an actual sitemap record (first one)
print("\n=== SITEMAP SAMPLE RECORD (ALL FIELDS) ===")
r = requests.get(f'{base}/sitemaps?$top=1', headers=h)
if r.status_code == 200:
    records = r.json().get('value', [])
    if records:
        for k, v in sorted(records[0].items()):
            if not k.startswith('@'):
                val_str = repr(v)[:150]
                print(f"  {k}: {val_str}")

# 3. Check an existing SYSTEM app's full record  
print("\n=== SYSTEM APP (PowerPlatformEnvironmentSettings) ===")
sys_id = "1014c929-983d-f111-88b5-000d3a3b279b"
r = requests.get(f'{base}/appmodules({sys_id})', headers=h)
if r.status_code == 200:
    for k, v in sorted(r.json().items()):
        if not k.startswith('@odata'):
            val_str = repr(v)[:150]
            print(f"  {k}: {val_str}")

# 4. Check if that system app has a linked sitemap via filter
print("\n=== SITEMAPS LINKED TO SYSTEM APP ===")
r = requests.get(f'{base}/sitemaps?$top=10&$select=sitemapid,sitemapname,sitemapnameunique,isappaware', headers=h)
if r.status_code == 200:
    for s in r.json().get('value', []):
        print(f"  {json.dumps(s)}")
else:
    # try without the select in case property names are wrong
    r2 = requests.get(f'{base}/sitemaps?$top=3', headers=h)
    if r2.status_code == 200:
        for s in r2.json().get('value', []):
            keys = [k for k in s.keys() if not k.startswith('@')]
            print(f"  Keys: {keys}")

# 5. Try getting app module navigation/sitemap properties
print("\n=== APPMODULE NAVIGATION PROPERTIES ===")
r = requests.get(f'{base}/EntityDefinitions(LogicalName=\'appmodule\')?$expand=OneToManyRelationships($select=SchemaName,ReferencingEntity)', headers=h)
if r.status_code == 200:
    rels = r.json().get('OneToManyRelationships', [])
    for rel in rels:
        print(f"  nav: {rel['SchemaName']} -> {rel['ReferencingEntity']}")
