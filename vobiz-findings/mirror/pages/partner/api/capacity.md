> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz partner CPS and concurrency allocation

> Transfer and reclaim CPS and concurrent-call capacity between your Vobiz partner account and customer accounts.

[← Partner API reference](/docs/partner/api)

Base URL: `https://api.vobiz.ai`

CPS and concurrency use the sames endpoints. Select the resource using `resource` in the request body.

## Authentication

Use the **partner account's** credentials:

```http theme={null}
X-Auth-ID: <PARTNER_AUTH_ID>
X-Auth-Token: <PARTNER_AUTH_TOKEN>
```

Put the **customer account's auth ID** in the URL. Do not use the customer's credentials for these partner operations.

## Endpoints

| Operation | Method | Path |
| - | - | - |
| Transfer capacity from partner to customer | POST | `/api/v1/partner/accounts/{CUSTOMER_AUTH_ID}/concurrency/transfer` |
| Reclaim capacity from customer to partner | POST | `/api/v1/partner/accounts/{CUSTOMER_AUTH_ID}/concurrency/reclaim` |
| View customer allocation and both accounts' limits | GET | `/api/v1/partner/accounts/{CUSTOMER_AUTH_ID}/concurrency` |
| List transfer history | GET | `/api/v1/partner/concurrency/transfers?limit=50&offset=0` |

Despite the `concurrency` path name, these endpoints support both resources.

## Transfer request

| Field | Type | Required | Meaning |
| - | - | - | - |
| `resource` | string | No | `concurrent_calls` (default) or `cps`. Set explicitly for clarity. |
| `slots` | integer | Yes | Amount to move, from 1 through 10,000. |
| `description` | string | No | Optional explanation, maximum 500 characters. |

A transfer subtracts `slots` from the partner's selected limit and adds that amount to the customer's selected limit. It does not set the customer's limit to `slots`. Transfer CPS and concurrent-call capacity in separate requests.

### Transfer 100 concurrent-call slots

```bash theme={null}
curl --request POST \
  "https://api.vobiz.ai/api/v1/partner/accounts/$CUSTOMER_AUTH_ID/concurrency/transfer" \
  --header "X-Auth-ID: $PARTNER_AUTH_ID" \
  --header "X-Auth-Token: $PARTNER_AUTH_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{
    "resource": "concurrent_calls",
    "slots": 100,
    "description": "Allocate 100 ports to customer"
  }'
```

### Transfer 10 CPS

```bash theme={null}
curl --request POST \
  "https://api.vobiz.ai/api/v1/partner/accounts/$CUSTOMER_AUTH_ID/concurrency/transfer" \
  --header "X-Auth-ID: $PARTNER_AUTH_ID" \
  --header "X-Auth-Token: $PARTNER_AUTH_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{
    "resource": "cps",
    "slots": 10,
    "description": "Allocate 10 CPS to customer"
  }'
```

## Transfer response

| Field | Meaning |
| - | - |
| `success` | Whether the operation succeeded. |
| `slots` | Amount transferred. |
| `resource` | Resource affected. |
| `from_account` | Source account auth ID for a transfer. |
| `to_account` | Destination account auth ID for a transfer. |
| `transfer_reference` | Generated ledger reference. |
| `partner_remaining` | Partner's selected limit after the operation. |
| `customer_effective` | Customer's selected limit after the operation. |
| `message` | Result description. |

## Reclaim capacity

Use the same request format with `/concurrency/reclaim`. For example, reclaim 5 CPS:

```bash theme={null}
curl --request POST \
  "https://api.vobiz.ai/api/v1/partner/accounts/$CUSTOMER_AUTH_ID/concurrency/reclaim" \
  --header "X-Auth-ID: $PARTNER_AUTH_ID" \
  --header "X-Auth-Token: $PARTNER_AUTH_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"resource":"cps","slots":5,"description":"Return 5 CPS to partner"}'
```

Reclaim reduces the customer's selected limit and restores capacity to the partner. It cannot exceed the net capacity previously allocated by this partner for that resource or the customer's current limit.

## View allocations

```bash theme={null}
curl --request GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/$CUSTOMER_AUTH_ID/concurrency" \
  --header "X-Auth-ID: $PARTNER_AUTH_ID" \
  --header "X-Auth-Token: $PARTNER_AUTH_TOKEN"
```

Response fields:

```text theme={null}
partner_auth_id
customer_auth_id
partner_concurrent_calls_limit
customer_concurrent_calls_limit
net_concurrent_calls_allocated
partner_cps_limit
customer_cps_limit
net_cps_allocated
```

## Transfer history

```bash theme={null}
curl --request GET \
  "https://api.vobiz.ai/api/v1/partner/concurrency/transfers?limit=50&offset=0" \
  --header "X-Auth-ID: $PARTNER_AUTH_ID" \
  --header "X-Auth-Token: $PARTNER_AUTH_TOKEN"
```

`limit` defaults to 50 and supports 1–200. `offset` defaults to 0. Entries are returned newest first.

## Requirements and behaviour

* The authenticated account must be an active partner.
* The partner must have limit-transfer access enabled for both resources. Contact [support@vobiz.ai](mailto:support@vobiz.ai) if this access is not enabled.
* The customer must belong to the authenticated partner and must not itself be a partner.
* The partner must have enough capacity for the requested transfer.
* Each transfer updates both accounts together.
* Updated limits are refreshed after the transfer. Allow up to five minutes if the immediate refresh is delayed.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.