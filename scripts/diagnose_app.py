"""Diagnose why PublishAppModule fails with validation errors."""
import msal, os, requests, json

app = msal.ConfidentialClientApplication(os.environ['AZURE_CLIENT_ID'],
    authority='https://login.microsoftonline.com/' + os.environ['AZURE_TENANT_ID'],
    client_credential=os.environ['AZURE_CLIENT_SECRET'])
t = app.acquire_token_for_client(scopes=[os.environ['DATAVERSE_URL'] + '/.default'])['access_token']
base = os.environ['DATAVERSE_URL'].rstrip('/') + '/api/data/v9.2'
h = {'Authorization': 'Bearer ' + t, 'OData-Version': '4.0',
     'Content-Type': 'application/json', 'Accept': 'application/json'}

# Find the latest AccessMigrated app
r = requests.get(f'{base}/appmodules?$select=appmoduleid,uniquename,appmoduleidunique,name,statecode,statuscode,navigationtype',
                 headers=h)
apps = [a for a in r.json().get('value', []) if 'AccessMigrated' in a.get('uniquename', '') or 'Access Migrated' in a.get('name', '')]
if not apps:
    print("No AccessMigrated app found! Listing all apps:")
    for a in r.json().get('value', []):
        print(f"  {a.get('uniquename')} / {a.get('name')} id={a.get('appmoduleid')}")
    exit(1)
app_rec = apps[0]
app_id = app_rec['appmoduleid']
app_uid = app_rec['appmoduleidunique']
print(f"App: {app_rec['uniquename']} id={app_id} unique={app_uid}")
print(f"  statecode={app_rec.get('statecode')} statuscode={app_rec.get('statuscode')} navtype={app_rec.get('navigationtype')}")

# 1. Try ValidateAppModule (different name)
print("\n=== ValidateAppModule ===")
for action_name in ['ValidateApp', 'ValidateAppModule', 'Microsoft.Dynamics.CRM.ValidateApp']:
    r = requests.post(f'{base}/{action_name}', json={"AppModuleId": app_id}, headers=h)
    if r.status_code != 404:
        print(f"  {action_name}: {r.status_code} {r.text[:500]}")
        break
    # Try as bound action
    r2 = requests.post(f'{base}/appmodules({app_id})/{action_name}', json={}, headers=h)
    if r2.status_code != 404:
        print(f"  Bound {action_name}: {r2.status_code} {r2.text[:500]}")
        break

# 2. RetrieveAppComponents — see what's actually in the app
print("\n=== RetrieveAppComponents ===")
r = requests.post(f'{base}/RetrieveAppComponents', json={"AppModuleId": app_id}, headers=h)
if r.status_code < 400:
    data = r.json()
    components = data.get('AppComponents', data.get('value', []))
    print(f"  Found {len(components)} components")
    for c in components[:15]:
        print(f"  {json.dumps(c)[:200]}")
else:
    print(f"  {r.status_code}: {r.text[:300]}")

# 3. Check components via navigation property
print("\n=== Components via navigation ===")
r = requests.get(f'{base}/appmodules({app_id})/appmodule_appmodulecomponent?$top=15',
                 headers=h)
if r.status_code == 200:
    for c in r.json().get('value', []):
        ct = c.get('componenttype')
        oid = c.get('objectid')
        print(f"  type={ct} objectid={oid}")
else:
    print(f"  {r.status_code}: {r.text[:200]}")

# 4. Check if our tables have forms and views
print("\n=== Forms/Views for auto_customers ===")
r = requests.get(f"{base}/EntityDefinitions(LogicalName='auto_customers')?$select=MetadataId", headers=h)
if r.status_code == 200:
    eid = r.json()['MetadataId']
    # Check systemforms
    r2 = requests.get(f"{base}/systemforms?$filter=objecttypecode eq 'auto_customers'&$select=name,type,formid&$top=5", headers=h)
    if r2.status_code == 200:
        forms = r2.json().get('value', [])
        print(f"  Forms: {len(forms)}")
        for f in forms:
            print(f"    {f.get('name')} type={f.get('type')} id={f.get('formid')}")
    else:
        print(f"  Forms query: {r2.status_code} {r2.text[:200]}")

    # Check savedqueries (views)
    r3 = requests.get(f"{base}/savedqueries?$filter=returnedtypecode eq 'auto_customers'&$select=name,savedqueryid,querytype&$top=5", headers=h)
    if r3.status_code == 200:
        views = r3.json().get('value', [])
        print(f"  Views: {len(views)}")
        for v in views:
            print(f"    {v.get('name')} querytype={v.get('querytype')} id={v.get('savedqueryid')}")
    else:
        print(f"  Views query: {r3.status_code} {r3.text[:200]}")

# 5. Check descriptor for validation info
print("\n=== App descriptor (first 500 chars) ===")
r = requests.get(f'{base}/appmodules({app_id})?$select=descriptor,configxml', headers=h)
if r.status_code == 200:
    d = r.json()
    desc = d.get('descriptor', '') or ''
    cfg = d.get('configxml', '') or ''
    print(f"  descriptor: {desc[:500]}")
    print(f"  configxml: {cfg[:500]}")
