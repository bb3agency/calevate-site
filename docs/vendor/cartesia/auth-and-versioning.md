# Cartesia — authentication and API versioning

## Host

`https://api.cartesia.ai`

* **VERIFIED-SDK** — `cartesia-ai/line`, `line/knowledge_base.py:13`:
  `DEFAULT_BASE_URL = "https://api.cartesia.ai"`, overridable by `CARTESIA_BASE_URL`.
* **VERIFIED-SDK** — `cartesia-ai/cartesia-python`, `src/cartesia/_client.py:127-130`:
  `base_url` falls back to `os.environ["CARTESIA_BASE_URL"]` then to
  `https://api.cartesia.ai`.

## Authentication: `Authorization: Bearer <api key>`

* **VERIFIED-SDK** — `cartesia-python/src/cartesia/_client.py:232-236`:

  ```python
  def _api_key_auth(self) -> dict[str, str]:
      api_key = self.api_key
      ...
      return {"Authorization": f"Bearer {api_key}"}
  ```

  `auth_headers` (`:221`) merges token auth and API-key auth, and both produce
  `Authorization: Bearer …`. This is the client through which `client.agents.*` runs, so
  it is direct evidence about the **agents** surface, not only about TTS.
* **VERIFIED-SDK, cross-checked** — `cartesia-js/src/client.ts:349,353`: the same two
  `Authorization: Bearer …` builders. Two generators, one spec.
* The key format is `sk_car_…` (REPORTED-DOCS, and stated in a third-party mirror; not
  load-bearing — we never parse the key).

### `X-API-Key` is a second, older published form — and it also appears on `/agents/*`

* **VERIFIED-SDK (Cartesia's own repo, prose)** — `cartesia-ai/skills`,
  `skills/line-voice-agent/references/calls-api.md:18-22`:

  ```bash
  curl -X POST https://api.cartesia.ai/agents/access-token \
    -H "X-API-Key: YOUR_CARTESIA_API_KEY" ...
  ```

* **REPORTED-DOCS** — the outbound-dialing page summary also shows `X-API-Key`.

**What we do about the disagreement.** The adapter sends `Authorization: Bearer`. It is
the form both *generated* clients use for every operation including `client.agents.*`,
and generated clients track the current spec; the `X-API-Key` sightings sit next to
older `Cartesia-Version` values (see below), which is what a superseded auth form looks
like. Being wrong here is loud (401 on every request), which is the safe direction. The
alternative — sending both headers — was rejected: two credentials-bearing headers for
one secret is two ways to do one thing, and it would hide which one the vendor actually
honoured at exactly the moment we most need to know.

## Version pin: `Cartesia-Version: 2026-08-14`

Every request carries a date-versioned header. Three different values are published, and
the spread is itself the finding — this axis moves.

| Value | Source | Standing |
|---|---|---|
| `2026-08-14` | `cartesia-python/src/cartesia/_client.py:244` and `:527` (`"cartesia-version": "2026-08-14"` in `default_headers`); `cartesia-js/src/client.ts:801`; `cartesia-mcp/cartesia_mcp/api_version.py` (`CARTESIA_VERSION = os.getenv("CARTESIA_VERSION", "2026-08-14")`, commented *"Latest stable version in docs (docs.json API Reference tab)"*) | **VERIFIED-SDK, three independent Cartesia repos.** This is what the adapter pins. |
| `2026-03-01` | outbound-dialing docs page | REPORTED-DOCS |
| `2025-04-16` | `cartesia-ai/skills`, `calls-api.md:41,180` (WebSocket Calls API example) | VERIFIED-SDK but plainly older |

### `2026-04-03` is NOT an API version, and citing it as one was our own error

`cartesia-ai/line`, `line/voice_agent_app.py:129` defines `CARTESIA_VERSION = "2026-04-03"`.
Reading its only use (`voice_agent_app.py:217`) settles what it is:

```python
response = {
    "websocket_url": self.ws_route,
    "cartesia_version": CARTESIA_VERSION,
    "metadata": metadata,
}
```

That is the body **our agent program returns to Cartesia's harness** from `POST /chats`,
declaring which *websocket wire protocol* the deployed agent speaks. It travels
agent → harness, it is a body field rather than a header, and it versions the in-call
protocol rather than the REST control plane. The adapter previously pinned it as
`Cartesia-Version` on every control-plane request, with a comment saying the harness
"sends it on every call setup" — both halves were wrong. Corrected under D-270.
