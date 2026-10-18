> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# SDKs

> Typed TypeScript and Python clients for every endpoint, with retries, idempotency and pagination built in.

Two small clients are generated from the same OpenAPI document as this reference, so every
endpoint here has a method, with typed request bodies and responses.

| | TypeScript | Python |
| - | - | - |
| Package | `@thinnestai/sdk` | `thinnestai` |
| Runtime | Node 18.17+, Deno, Bun, browsers — the global `fetch`, no dependencies | Python 3.9+, `httpx` only |
| Clients | `Client` | `Client` and `AsyncClient`, the same shape |

<Warning>
  The packages are **not yet published to npm or PyPI**. Until they are, install them from a copy of
  the repository:

  ```bash theme={null}
  npm install ./sdks/typescript      # TypeScript
  pip install ./sdks/python          # Python
  ```

  The compiled `dist/` is not committed, so installing from a path builds it: the package's
  `prepare` script fetches the TypeScript compiler with `npx` (the machine needs network access
  the first time) and compiles `src/`. If your npm blocks install scripts, or you copied the
  folder instead of installing it, run `npm install && npm run build` inside it once.
</Warning>

## Quickstart

<CodeGroup>
  ```ts TypeScript theme={null}
  import { Client, ApiError } from "@thinnestai/sdk";

  const client = new Client({ apiKey: process.env.API_KEY! });

  // Create an agent
  const agent = await client.agents.create({ name: "Skyline Sales" });

  // Place a call
  const call = await client.calls.place({
    to: "+91 98765 43210",
    purpose: "I'm calling from Skyline Homes about your enquiry.",
    agent: agent.id,
  });

  // Act in one of your customers' workspaces
  const customer = await client.customers.create({ name: "Sunrise Dental Clinic" });
  const sunrise = client.withWorkspace(customer.id);
  await sunrise.agents.list();
  ```

  ```python Python theme={null}
  import os
  from thinnestai import Client, ApiError

  client = Client(os.environ["API_KEY"])

  # Create an agent
  agent = client.agents.create({"name": "Skyline Sales"})

  # Place a call
  call = client.calls.place({
      "to": "+91 98765 43210",
      "purpose": "I'm calling from Skyline Homes about your enquiry.",
      "agent": agent["id"],
  })

  # Act in one of your customers' workspaces
  customer = client.customers.create({"name": "Sunrise Dental Clinic"})
  sunrise = client.with_workspace(customer["id"])
  sunrise.agents.list()
  ```
</CodeGroup>

`withWorkspace` / `with_workspace` sends the `Thinnest-Workspace` header on every request (see
[Customers](/api-reference/customers)). The `customers.*` methods and `usage.getCustomers` ignore it, because those endpoints are always
called as you, never as one of your customers. To fix one workspace for a whole client, pass
`workspace: "org_…"` (TypeScript) or `workspace="org_…"` (Python) when you create it.

## How methods are named

One namespace per group in this reference — `agents`, `calls`, `customers`, `phoneNumbers`
(`phone_numbers` in Python), `webhooks`, … — and a method per endpoint, named for what it does:
`client.agents.list()`, `client.calls.place(…)`, `client.customers.restore(id)`.

* Path parameters come first, then the request body.
* TypeScript takes query parameters as an object after the body, then `RequestOptions`
  (`idempotencyKey`, `headers`, `signal`, `timeoutMs`, `maxRetries`).
* Python takes query parameters as keyword arguments (`client.calls.list(status="completed")`),
  plus `extra_headers=`, `timeout=` and, where the endpoint accepts one, `idempotency_key=`.
* Binary answers (call recordings, voice previews) come back as a `Blob` / `bytes`; text answers
  (a transcript as text, a CSV export) as a string.

## Pagination

List endpoints answer one page, `{ items, nextCursor }`. Each has a companion that walks every page:

<CodeGroup>
  ```ts TypeScript theme={null}
  for await (const agent of client.agents.listAll({ limit: 100 })) {
    console.log(agent.name);
  }
  ```

  ```python Python theme={null}
  for agent in client.agents.list_all(limit=100):
      print(agent["name"])

  # AsyncClient
  async for agent in client.agents.list_all():
      print(agent["name"])
  ```
</CodeGroup>

## Errors

Any answer outside `2xx` raises `ApiError`, carrying `status`, `message` (the `error` sentence
from [the error body](/api-reference/errors)), the response `headers` and the parsed `body`. No
answer at all — the network failed or the request timed out — raises `ApiConnectionError`.

## Retries and idempotency

The clients follow the [retry policy](/api-reference/errors) for you:

* `429` is retried for every method, waiting for `Retry-After` (up to 120 seconds; a longer wait is
  thrown rather than retried early).
* `408`, `500`, `502`, `503`, `504` and network errors are retried only for `GET` and `HEAD`, and for
  any request sent with an `Idempotency-Key`. A `POST`, `PUT`, `PATCH` or `DELETE` without one is
  never replayed, because replaying it could act twice.
* Backoff is exponential with jitter, capped at 8 seconds; two retries by default (`maxRetries` /
  `max_retries`).
* These get an `Idempotency-Key` generated when you give none: `calls.place`, `calls.placeBatch`,
  `conversations.reply`, `messages.send`, `codes.send` and `customers.create`. **The same key is
  sent on every retry**, so a retry never places a second call. A key you pass — as the
  `idempotencyKey` option or the `idempotencyKey` body field — is the one sent.
* `400`, `401`, `403`, `404` and `409` are never retried.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.