> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Phone numbers (you can't port from Plivo)

> When migrating from Plivo to Vobiz you cannot port or transfer your Plivo numbers - there is no porting flow. Buy new Vobiz numbers from inventory and re-point your call flows. Covers the buy flow and the 15-day DID cool-off.

<Warning>
  **You cannot port (transfer) a phone number from Plivo to Vobiz.** There is no number-porting process. Your Plivo numbers stay on Plivo. To run on Vobiz, **buy new Vobiz numbers** and update your call flows and caller IDs to use them.
</Warning>

When you migrate from Plivo, treat phone numbers as a fresh provision on Vobiz, not a transfer. Buy the numbers you need from Vobiz inventory, route them, cut your traffic over, and then release the old numbers on Plivo once you no longer need them.

## Buy new Vobiz numbers

Buying a number on Vobiz is a two-step flow: browse inventory, then purchase by E.164. For the full walkthrough (console **and** API, fees, India series, and routing), see **[Buy a phone number](/docs/buy-a-phone-number)**.

### 1. Browse inventory

```bash cURL - browse inventory theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/inventory/numbers?country=IN&search=80&page=1&per_page=25" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

Inspect `setup_fee` and `monthly_fee` (in the listed `currency`) on each result before you buy - these amounts are debited at purchase. See [List Inventory Numbers](/docs/account-phone-number/list-inventory-numbers).

### 2. Purchase by E.164

```python Python - purchase from inventory theme={null}
import requests

auth_id = "{auth_id}"
resp = requests.post(
    f"https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/purchase-from-inventory",
    headers={
        "X-Auth-ID": auth_id,
        "X-Auth-Token": "{auth_token}",
        "Content-Type": "application/json",
    },
    json={"e164": "+919876543210"},
)
resp.raise_for_status()
print(resp.json())
```

After purchase the number is owned by your account but not yet routed. Attach it to an application, [assign it to a trunk](/docs/trunks/assign-number), or [hand it to a sub-account](/docs/account-phone-number/assign-subaccount) to start receiving calls. See [Purchase from Inventory](/docs/account-phone-number/purchase-from-inventory) for the response shape and error cases.

<Note>
  India numbers follow series and compliance rules - 140 for promotional, 160 for transactional (BFSI), 1800 for toll-free, and so on. Pick the right series and review [India compliance](/docs/compliance/india) before you purchase.
</Note>

## Recommended cutover order

Because the numbers change, plan the switch so callers are never dropped:

<Steps>
  <Step title="Buy Vobiz numbers and route them">
    Provision new Vobiz numbers and wire them to your applications/trunks.
  </Step>

  <Step title="Update where your number is published">
    Point your app, CRM, website, IVR prompts, and outbound caller ID at the new Vobiz numbers.
  </Step>

  <Step title="Run both in parallel">
    Keep the Plivo numbers live during cutover so anyone using the old digits still connects while you validate Vobiz.
  </Step>

  <Step title="Cut over, then decommission Plivo">
    Once traffic is flowing on Vobiz, release the Plivo numbers on Plivo's side.
  </Step>
</Steps>

## Watch the 15-day DID cool-off

<Warning>
  When you move a DID back to the parent pool by [unassigning it from a sub-account](/docs/account-phone-number/unassign-subaccount), Vobiz enforces a **15-day cool-off** on recently active numbers. If the DID had a call within the last 15 days, the unassignment is rejected with `409 did_cool_off_in_effect` (the response includes `cool_off_until` and `cool_off_remaining_seconds`). A DID that was never used moves back immediately. Admins can override with `?force=true`, which writes an audit record.
</Warning>

## Next steps

<CardGroup cols={2}>
  <Card title="Buy a phone number" icon="phone" href="/docs/buy-a-phone-number">
    The complete step-by-step guide to provisioning a Vobiz number.
  </Card>

  <Card title="Cutover checklist" icon="list-check" href="/docs/guides/plivo-to-vobiz/cutover-checklist">
    The full step-by-step plan for switching production traffic to Vobiz.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.