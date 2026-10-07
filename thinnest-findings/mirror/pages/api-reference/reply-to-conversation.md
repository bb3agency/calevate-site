> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Reply to a conversation

> POST /api/v1/conversations/{id}/reply — your own agent answers a WhatsApp customer.

```http theme={null}
POST /api/v1/conversations/conv_e0829641-…/reply
Authorization: Bearer ta_live_…
Content-Type: application/json
Idempotency-Key: reply-7f3a91
```

```json theme={null}
{ "text": "Yes — it left our warehouse this morning. Tracking: AB123456." }
```

```json theme={null}
{ "ok": true }
```

Only for a number with [Connect External Agent/CRM](/whatsapp/external-agents) turned on.
`{id}` is the `conversationId` from the `message.received` delivery to your external agent's [address](/whatsapp/external-agents).

## Body

Send **exactly one** of these. Two in one call are refused, so a customer never
gets two messages when you meant one.

<ParamField body="text" type="string">
  Up to 4,096 characters. Only while the customer's 24-hour window is open.
</ParamField>

<ParamField body="media" type="object">
  A file WhatsApp fetches from your link. Only while the window is open.

  | Field | |
  | - | - |
  | `type` | `image`, `video`, `audio` or `file` |
  | `url` | A public `https://` link, up to 2,048 characters |
  | `caption` | Shown under an image or video. Optional |
  | `filename` | What a document is called on the customer's phone. Optional |

  WhatsApp's own [size and format limits](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media#supported-media-types)
  apply.
</ParamField>

<ParamField body="form" type="string">
  A published [WhatsApp form](/whatsapp/templates#forms), by the name it has on
  the Forms page — `"Delivery address"` — or `{ "name": "…" }`. It must belong
  to the agent the number is assigned to. Only while the window is open.
</ParamField>

<ParamField body="template" type="object">
  An approved [template](/whatsapp/templates). Works **after** the window has
  closed too.

  | Field | |
  | - | - |
  | `name` | The template's name |
  | `language` | e.g. `en`. Optional — the oldest approved language is used |
  | `variables` | The body's `{{1}}`, `{{2}}`… in order |
  | `buttonVariables` | A link button's placeholder, when it has one |
  | `headerMediaUrl` | The header's image, video or document, when it has one |

  It must be approved on **this conversation's number**. The same checks as
  [Send a message](/api-reference/send-message) apply, including opt-outs for
  marketing templates.
</ParamField>

## Idempotency

Send an `Idempotency-Key` header, as on every endpoint that sends. A retry with
the same key gets the first answer back and sends nothing. A `502` releases the
key, so the same retry can succeed.

## Errors

| Status | Why |
| - | - |
| `400` | No kind, more than one kind, or a field that is not valid |
| `402` | Your Free plan's 200 WhatsApp messages are used. Switch to Pay as you go |
| `404` | The conversation is not in your workspace, or the template or form does not exist |
| `409` | Connect External Agent/CRM is off for this number · a teammate has taken the conversation over · the 24-hour window has closed (send a template) · the template is not approved or is for another number · the customer opted out · the number is disconnected |
| `429` | Too many requests. Wait and retry |
| `502` | WhatsApp refused the message. Retry with the same key |

Every error body is `{ "error": "…" }` in plain words. See [errors](/api-reference/errors).

## Pricing

Each message is charged at 10% of Meta's rate, and Meta bills your WhatsApp
account for its own fee. See [Connect External Agent/CRM](/whatsapp/external-agents#pricing).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.