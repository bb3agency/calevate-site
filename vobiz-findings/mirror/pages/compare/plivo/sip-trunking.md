> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Plivo Zentrunk → Vobiz SIP Trunking Migration

> Map Plivo Zentrunk trunks, IP access lists, credentials, and origination URIs to Vobiz trunks, ip_access_control_list, credentials, and origination_uri - with before/after code for outbound and inbound trunks.

Plivo exposes SIP trunking through **Zentrunk** (REST-only resources under `/Zentrunk/`, no SDK helpers). Vobiz models the same primitives as typed, SDK-backed resources - `trunks`, `ip_access_control_list`, `credentials`, and `origination_uri`.

<Note>
  Vobiz base URL is `https://api.vobiz.ai/api/v1` and every path is account-scoped: `/Account/{auth_id}/trunks`. Plivo Zentrunk lives at `https://api.plivo.com/v1/Account/{auth_id}/Zentrunk/…`.
</Note>

## Plivo → Vobiz mapping

| Operation | Plivo Zentrunk (REST) | Vobiz REST | Vobiz SDK (Python / Node) |
| - | - | - | - |
| Create trunk | `POST /Zentrunk/Trunk/` | `POST /trunks` | `trunks.create_trunk` / `trunks.createTrunk` |
| List trunks | `GET /Zentrunk/Trunk/` | `GET /trunks` | `trunks.list_trunks` / `trunks.listTrunks` |
| Retrieve trunk | `GET /Zentrunk/Trunk/{uuid}/` | `GET /trunks/{trunk_id}` | `trunks.retrieve_trunk` / `trunks.retrieveTrunk` |
| Update trunk | `POST /Zentrunk/Trunk/{uuid}/` | `PUT /trunks/{trunk_id}` | `trunks.update_trunk` / `trunks.updateTrunk` |
| Delete trunk | `DELETE /Zentrunk/Trunk/{uuid}/` | `DELETE /trunks/{trunk_id}` | `trunks.delete_trunk` / `trunks.deleteTrunk` |
| Create IP ACL | `POST /Zentrunk/IPAccessControlList/` | `POST /ip-acl` | `ip_access_control_list.create_ip_acl` / `ipAccessControlList.createIpAcl` |
| List IP ACLs | `GET /Zentrunk/IPAccessControlList/` | `GET /trunks/ip-acl` | `ip_access_control_list.list_ip_acls` / `ipAccessControlList.listIpAcls` |
| Update IP ACL | `POST /Zentrunk/IPAccessControlList/{uuid}/` | `PUT /ip-acl/{ip_acl_id}` | `ip_access_control_list.update_ip_acl` / `ipAccessControlList.updateIpAcl` |
| Delete IP ACL | `DELETE /Zentrunk/IPAccessControlList/{uuid}/` | `DELETE /ip-acl/{ip_acl_id}` | `ip_access_control_list.delete_ip_acl` / `ipAccessControlList.deleteIpAcl` |
| Create credential | `POST /Zentrunk/Credential/` | `POST /credentials` | `credentials.create_credential` / `credentials.createCredential` |
| List credentials | `GET /Zentrunk/Credential/` | `GET /trunks/credentials` | `credentials.list_credentials` / `credentials.listCredentials` |
| Update credential (password) | `POST /Zentrunk/Credential/{uuid}/` | `PUT /credentials/{credential_id}` | `credentials.update_credential` / `credentials.updateCredential` |
| Delete credential | `DELETE /Zentrunk/Credential/{uuid}/` | `DELETE /credentials/{credential_id}` | `credentials.delete_credential` / `credentials.deleteCredential` |
| Create origination URI | `POST /Zentrunk/URI/` | `POST /origination-uris` | `origination_uri.create_origination_uri` / `originationUri.createOriginationUri` |
| List origination URIs | `GET /Zentrunk/URI/` | `GET /trunks/origination-uris` | `origination_uri.list_origination_uris` / `originationUri.listOriginationUris` |
| Update origination URI | `POST /Zentrunk/URI/{uuid}/` | `PUT /origination-uris/{id}` | `origination_uri.update_origination_uri` / `originationUri.updateOriginationUri` |
| Delete origination URI | `DELETE /Zentrunk/URI/{uuid}/` | `DELETE /origination-uris/{id}` | `origination_uri.delete_origination_uri` / `originationUri.deleteOriginationUri` |
| Route a DID into an inbound trunk | `Number` app/console binding | `POST /Number/{number}/` | `phone_numbers.assign_number_to_trunk` / `phoneNumbers.assignNumberToTrunk` |

## Before / after: bring up an outbound trunk

An outbound trunk lets your PBX/SBC send calls *to* the carrier. You (1) create an auth method - an IP ACL or a username/password credential - and (2) create the trunk.

### Plivo (cURL - no SDK)

```bash theme={null}
# 1. Whitelist your SBC IPs (one ACL holds many IPs)
curl -i --user "$AUTH_ID:$AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Prod SBC","ip_addresses":["203.0.113.10","203.0.113.11"]}' \
  https://api.plivo.com/v1/Account/$AUTH_ID/Zentrunk/IPAccessControlList/

# 2. Create the outbound trunk, binding the auth method by UUID
curl -i --user "$AUTH_ID:$AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"My Outbound Trunk","trunk_direction":"outbound","ipacl_uuid":"<IPACL_UUID>"}' \
  https://api.plivo.com/v1/Account/$AUTH_ID/Zentrunk/Trunk/
```

### Vobiz (Python SDK)

```python theme={null}
from vobiz import Vobiz

client = Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)

# 1. Whitelist SBC IPs - one rule per IP/CIDR (CIDR supported)
client.ip_access_control_list.create_ip_acl(
    auth_id=AUTH_ID, name="Prod SBC", ip_address="203.0.113.0/24",
)

# 2. Create the outbound trunk
trunk = client.trunks.create_trunk(
    auth_id=AUTH_ID,
    name="My Outbound Trunk",
    trunk_type="OUTBOUND",
    max_concurrent_calls=10,
)
# Send calls to trunk.trunk_domain, e.g. <uuid>.sip.vobiz.ai
```

<Note>
  **Binding model difference:** Plivo passes `ipacl_uuid` / `credential_uuid` **inside the trunk-create body**. Vobiz IP ACLs and credentials are **account-scoped** - `create_trunk` accepts `name`, `trunk_type`, and `max_concurrent_calls`; the trunk is identified by its returned `trunk_domain`, and any account credential/IP rule authenticates against it.
</Note>

## Key differences & gotchas

* **Auth header, not Basic Auth.** Vobiz uses `X-Auth-ID` / `X-Auth-Token` headers (set by the SDK) instead of Plivo's HTTP Basic `--user AUTH_ID:AUTH_TOKEN`.
* **Updates are `PUT`, not re-`POST`.** Vobiz uses a proper `PUT` for `update_trunk`, `update_credential`, `update_ip_acl`, and `update_origination_uri`.
* **Per-rule IP/CIDR model.** Vobiz `create_ip_acl` uses one rule per `ip_address` with CIDR support, so a Plivo `ip_addresses` array maps cleanly to one CIDR block or a set of rules.
* **Direction is a type, and `both` exists.** Vobiz `create_trunk` takes `trunk_type` (`OUTBOUND`/`INBOUND`); the stored `trunk_direction` can also be `both`.
* **Flexible origination routing.** Model primary/secondary destinations as multiple `origination_uri` records ordered by `priority`/`weight`.
* **Account-scoped auth.** IP ACLs and credentials are account-scoped, so any account credential or IP rule authenticates against your trunks.
* **`secure` / `transport` on the trunk object.** Set these via `update_trunk` or account defaults.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.