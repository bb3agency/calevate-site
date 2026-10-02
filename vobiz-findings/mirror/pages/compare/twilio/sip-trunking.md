> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Twilio Elastic SIP Trunking → Vobiz SIP Trunking

> Migrate from Twilio Elastic SIP Trunking to Vobiz. Map trunking.v1.trunks, origination_urls, credential_lists, and ip_access_control_lists to Vobiz's first-class, typed SDK resources - trunks, origination_uri, credentials, and ip_access_control_list - with side-by-side Python and Node.

Twilio models a SIP trunk as a container (`trunking.v1.trunks`) that you decorate with **origination URLs**, **credential lists**, and **IP access control lists** - but the credential lists and IP ACLs actually live in a *different* API namespace (`api.v2010.account.sip.*`) and are only *associated* with the trunk by SID. Vobiz collapses that split: **every trunking concept is a first-class, typed SDK resource** - `trunks`, `credentials`, `ip_access_control_list`, and `origination_uri` - all account-scoped by an explicit `auth_id`. Migration is a resource-for-resource rename plus dropping the cross-namespace association dance.

<Note>
  `AUTH_ID` is your Vobiz Auth ID (`MA_…`) and `AUTH_TOKEN` your Auth Token. In the Vobiz SDK, `api_key` **is** the Auth ID (sent as `X-Auth-ID`) and `auth_token` is sent as `X-Auth-Token`. Every trunking method takes `auth_id` explicitly. Base URL: `https://api.vobiz.ai/api/v1`.
</Note>

## Twilio → Vobiz mapping

| Twilio (Elastic SIP Trunking) | Vobiz | Notes |
| - | - | - |
| `client.trunking.v1.trunks.create()` | `client.trunks.create_trunk(auth_id, name=, trunk_type=, max_concurrent_calls=)` | The trunk container. `trunk_type` is `"INBOUND"` / `"OUTBOUND"`. |
| `client.trunking.v1.trunks.list()` | `client.trunks.list_trunks(auth_id)` | List every trunk on the account. |
| `client.trunking.v1.trunks(sid).fetch()` | `client.trunks.retrieve_trunk(auth_id, trunk_id=)` | Fetch one trunk. |
| `client.trunking.v1.trunks(sid).update(...)` | `client.trunks.update_trunk(auth_id, trunk_id=, name=, max_concurrent_calls=, enabled=)` | Rename, re-cap concurrency, enable/disable. |
| `client.trunking.v1.trunks(sid).delete()` | `client.trunks.delete_trunk(auth_id, trunk_id=)` | Remove the trunk. |
| Concurrent-call channels (account/CPS limits) | `max_concurrent_calls=` on the trunk | Concurrency is set directly on each Vobiz trunk. |
| `sip.credential_lists.create()` + `.credentials.create(username, password)` + `trunks(sid).credentials_lists.create(credential_list_sid)` | `client.credentials.create_credential(auth_id, username=, password=)` | One typed call - no separate list object to create and then associate. |
| `sip.credential_lists(cl).credentials.list()` | `client.credentials.list_credentials(auth_id)` | List SIP credentials. |
| `sip.credential_lists(cl).credentials(cr).update(password=)` | `client.credentials.update_credential(auth_id, credential_id=, password=)` | Rotate a password. |
| `sip.credential_lists(cl).credentials(cr).delete()` | `client.credentials.delete_credential(auth_id, credential_id=)` | Delete a credential. |
| `sip.ip_access_control_lists.create()` + `.ip_addresses.create(ip_address)` + `trunks(sid).ip_access_control_lists.create(ip_access_control_list_sid)` | `client.ip_access_control_list.create_ip_acl(auth_id, name=, ip_address=)` | IP-based termination auth in one call. |
| `sip.ip_access_control_lists(al).ip_addresses.list()` | `client.ip_access_control_list.list_ip_acls(auth_id)` | List allowed source IPs. |
| `ip_access_control_lists(al).ip_addresses(ip).update(...)` | `client.ip_access_control_list.update_ip_acl(auth_id, ip_acl_id=, ...)` | Change an allowed IP. |
| `ip_access_control_lists(al).ip_addresses(ip).delete()` | `client.ip_access_control_list.delete_ip_acl(auth_id, ip_acl_id=)` | Revoke an IP. |
| `client.trunking.v1.trunks(sid).origination_urls.create(weight, priority, enabled, friendly_name, sip_url)` | `client.origination_uri.create_origination_uri(auth_id, name=, sip_uri=, priority=)` | Where inbound (origination) calls are delivered. |
| `origination_urls.list()` | `client.origination_uri.list_origination_uris(auth_id)` | List origination endpoints. |
| `origination_urls(ou).update(...)` | `client.origination_uri.update_origination_uri(auth_id, origination_uri_id=, ...)` | Repoint or re-prioritise. |
| `origination_urls(ou).delete()` | `client.origination_uri.delete_origination_uri(auth_id, origination_uri_id=)` | Remove an endpoint. |
| `disaster_recovery_url` on the trunk | A second `origination_uri` with a higher `priority` number | Add fallback SBCs as lower-priority origination URIs - Vobiz walks them in priority order. |
| `client.incoming_phone_numbers(sid).update(trunk_sid=...)` | `client.phone_numbers.assign_number_to_trunk(auth_id, phone_number=, trunk_group_id=)` | Route a purchased DID's inbound calls through the trunk. |
| Detach number from trunk | `client.phone_numbers.unassign_number_from_trunk(auth_id, phone_number=)` | Stop routing a DID through the trunk. |
| Account SID + Auth Token (HTTP Basic) | `X-Auth-ID` + `X-Auth-Token` headers (set once on the client) | |
| `trunking.twilio.com/v1` | `https://api.vobiz.ai/api/v1` | Trunking and voice share one Vobiz base URL. |
| Trunk-call CDRs (Voice Insights / call logs) | `client.cdr.list_cdrs(auth_id, sip_call_id=, from_number=, to_number=, start_date=, end_date=, ...)` | Query completed trunk calls, including by SIP Call-ID. |

## Create a trunk

Termination (outbound) and origination (inbound) both hang off one trunk object. In Vobiz you also set the concurrency cap right here.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.rest import Client

  client = Client(ACCOUNT_SID, AUTH_TOKEN)

  trunk = client.trunking.v1.trunks.create(
      friendly_name="My Outbound Trunk",
      domain_name="my-company.pstn.twilio.com",
  )
  print(trunk.sid)
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import Vobiz

  client = Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)

  trunk = client.trunks.create_trunk(
      auth_id=AUTH_ID,
      name="My Outbound Trunk",
      trunk_type="OUTBOUND",
      max_concurrent_calls=10,
  )
  print(trunk)
  ```

  ```javascript Vobiz · Node theme={null}
  import { VobizClient } from '@vobiz/sdk';

  const client = new VobizClient({ apiKey: AUTH_ID, authToken: AUTH_TOKEN });

  const trunk = await client.trunks.createTrunk(AUTH_ID, {
    name: 'My Outbound Trunk',
    trunk_type: 'OUTBOUND',
    max_concurrent_calls: 10,
  });
  ```
</CodeGroup>

## Termination auth - credentials and IP allow-lists

This is where the biggest simplification lands. On Twilio you create a credential list in the `api.v2010` namespace, add credentials to it, then make a *second* call to associate the list's SID with the trunk. Vobiz creates the credential (and the IP rule) as one typed call against the account.

<CodeGroup>
  ```python Twilio · Python theme={null}
  # 1) create the credential list, 2) add a credential, 3) associate with trunk
  cl = client.api.v2010.account.sip.credential_lists.create(
      friendly_name="Termination Users",
  )
  client.api.v2010.account.sip \
      .credential_lists(cl.sid) \
      .credentials.create(username="pbx01", password="S3cur3Pass!")

  client.trunking.v1.trunks(trunk.sid) \
      .credentials_lists.create(credential_list_sid=cl.sid)
  ```

  ```python Vobiz · Python theme={null}
  # one typed call - the credential is account-scoped and usable by your trunk
  cred = client.credentials.create_credential(
      auth_id=AUTH_ID,
      username="pbx01",
      password="S3cur3Pass!",
  )

  # rotate the password later
  client.credentials.update_credential(
      auth_id=AUTH_ID,
      credential_id=cred.id,
      password="Rotat3dPass!",
  )
  ```

  ```javascript Vobiz · Node theme={null}
  const cred = await client.credentials.createCredential(AUTH_ID, {
    username: 'pbx01',
    password: 'S3cur3Pass!',
  });

  await client.credentials.updateCredential(AUTH_ID, {
    credential_id: cred.id,
    password: 'Rotat3dPass!',
  });
  ```
</CodeGroup>

Prefer IP-based authentication for a static SBC? Same story - one call instead of three:

<CodeGroup>
  ```python Twilio · Python theme={null}
  al = client.api.v2010.account.sip.ip_access_control_lists.create(
      friendly_name="Datacenter SBCs",
  )
  client.api.v2010.account.sip \
      .ip_access_control_lists(al.sid) \
      .ip_addresses.create(friendly_name="SBC-1", ip_address="203.0.113.10")

  client.trunking.v1.trunks(trunk.sid) \
      .ip_access_control_lists.create(ip_access_control_list_sid=al.sid)
  ```

  ```python Vobiz · Python theme={null}
  client.ip_access_control_list.create_ip_acl(
      auth_id=AUTH_ID,
      name="SBC-1",
      ip_address="203.0.113.10",
  )
  ```

  ```javascript Vobiz · Node theme={null}
  await client.ipAccessControlList.createIpAcl(AUTH_ID, {
    name: 'SBC-1',
    ip_address: '203.0.113.10',
  });
  ```
</CodeGroup>

## Origination - where inbound calls are delivered

Twilio's origination URLs carry `weight` + `priority` + `enabled`. Vobiz's `origination_uri` carries a `priority`; add multiple URIs to get ordered failover (the lowest priority number is tried first), which is exactly how you'd replace a `disaster_recovery_url`.

<CodeGroup>
  ```python Twilio · Python theme={null}
  client.trunking.v1.trunks(trunk.sid).origination_urls.create(
      friendly_name="Primary SBC",
      sip_url="sip:sbc1.example.com",
      priority=10,
      weight=10,
      enabled=True,
  )
  client.trunking.v1.trunks(trunk.sid).origination_urls.create(
      friendly_name="Backup SBC",
      sip_url="sip:sbc2.example.com",
      priority=20,   # higher number = tried after primary
      weight=10,
      enabled=True,
  )
  ```

  ```python Vobiz · Python theme={null}
  client.origination_uri.create_origination_uri(
      auth_id=AUTH_ID,
      name="Primary SBC",
      sip_uri="sip:sbc1.example.com",
      priority=1,
  )
  client.origination_uri.create_origination_uri(
      auth_id=AUTH_ID,
      name="Backup SBC",
      sip_uri="sip:sbc2.example.com",
      priority=2,   # walked after the primary - your disaster-recovery path
  )
  ```

  ```javascript Vobiz · Node theme={null}
  await client.originationUri.createOriginationUri(AUTH_ID, {
    name: 'Primary SBC',
    sip_uri: 'sip:sbc1.example.com',
    priority: 1,
  });
  ```
</CodeGroup>

## Route a DID through the trunk

Once the trunk is provisioned, point a purchased number at it so inbound PSTN calls follow your origination URIs.

<CodeGroup>
  ```python Twilio · Python theme={null}
  number = client.incoming_phone_numbers.list(phone_number="+14155551234")[0]
  client.incoming_phone_numbers(number.sid).update(trunk_sid=trunk.sid)
  ```

  ```python Vobiz · Python theme={null}
  client.phone_numbers.assign_number_to_trunk(
      auth_id=AUTH_ID,
      phone_number="%2B14155551234",   # URL-encode the leading +
      trunk_group_id=trunk.id,
  )
  ```

  ```javascript Vobiz · Node theme={null}
  await client.phoneNumbers.assignNumberToTrunk(AUTH_ID, {
    phone_number: '%2B14155551234',
    trunk_group_id: trunk.id,
  });
  ```
</CodeGroup>

## Key differences

* **Every trunking concept is a typed, top-level SDK resource.** `trunks`, `credentials`, `ip_access_control_list`, and `origination_uri` are first-class clients with full CRUD - no reaching into a separate `api.v2010.account.sip.*` namespace and then associating SIDs back to the trunk.
* **One call for termination auth.** Creating a SIP credential (or an IP rule) is a single `create_credential` / `create_ip_acl` call, versus Twilio's create-list → add-item → associate-with-trunk three-step.
* **Concurrency lives on the trunk.** `max_concurrent_calls` is a plain field on `create_trunk`/`update_trunk`, so capacity is explicit per trunk and editable in place.
* **Disaster recovery is just priority.** Add lower-priority `origination_uri` entries and Vobiz walks them in order - the same fallback behaviour as Twilio's `disaster_recovery_url`, expressed with the resource you already use for origination.
* **Consistent account scoping.** Every method takes `auth_id` explicitly, so multi-account and sub-account trunk management is uniform across `trunks`, `credentials`, `origination_uri`, and number assignment.
* **Auth is header-based.** Set `X-Auth-ID` + `X-Auth-Token` once on the client instead of HTTP Basic on each request; the same client also drives voice, numbers, and CDRs.
* **Trunk-call visibility via CDRs.** `client.cdr.list_cdrs(auth_id, sip_call_id=…)` lets you query completed trunk calls - including by SIP Call-ID - from the same SDK.

<Tip>
  Migrating call-control flows too? [`<Gather>`](/docs/xml/gather) covers your IVR menus. See the full [Twilio → Vobiz overview](/docs/compare/twilio/overview) for the migration order across trunking, numbers, and voice.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.