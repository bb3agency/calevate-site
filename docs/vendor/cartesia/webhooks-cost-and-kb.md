# Cartesia — webhooks, cost metering, knowledge base

## Webhooks

### What is verified

* An agent can have one. **VERIFIED-SDK** — `cartesia-python/src/cartesia/types/agent_summary.py:80-84`:
  `webhook_id: Optional[str]`, *"The identifier for the webhook associated with the agent.
  Add or customize a webhook to your agent to receive events when calls are made to your
  agent via the Playground."* Same field in `cartesia-js/src/resources/agents/agents.ts:148-152`.
* Nothing else. There is **no webhook resource, no signing helper, no signature verifier
  and no event-type enum anywhere in `cartesia-python`, `cartesia-js`, `cartesia-mcp` or
  `line`.** A grep for `webhook` across all four returns the `webhook_id` field, an
  unrelated `http_server_tool` ("webhook tool") for outbound tool calls from inside a
  call, and test filenames.

### What is only reported

**REPORTED-DOCS**, one search summary of a Cartesia docs page:

> *"In your webhook handler, you should verify that all incoming requests have an
> `x-webhook-secret` header set to this secret value, to verify that the requests are
> coming from Cartesia."* … *"A webhook can be sent to a configurable endpoint when a call
> starts, completes or fails. Each payload includes the full transcript of the
> conversation."*

If that is right, the scheme is a **shared secret in a header**, not an HMAC over the
body. Those differ in what they protect: a shared secret proves the sender knows a token
and does nothing about replay or tampering; an HMAC binds the signature to the bytes.

### What the adapter does, and why it did not change

`CARTESIA_CAPABILITIES.webhook_auth` stays `"hmac"` and
`CartesiaEngine.verify_webhook` stays fail-closed (`ok=False`,
`reason="signature_scheme_unverified"`). Three reasons:

1. `WebhookAuthMethod` is `hmac | source_ip | none`. A shared-secret header is none of
   the three, and widening that Literal would ripple into `WEBHOOK_AUTH_BY_ENGINE`, the
   `apps/voice-runtime` receiver, `WebhookVerdict` and the conformance suite — a
   behavioural change on the strength of one search snippet, which is exactly what the
   evidence ladder forbids.
2. Both halves already fail CLOSED, so the declared label changes nothing a delivery
   experiences: the receiver refuses `hmac` deliveries until a real verifier exists, and
   the reconciliation poller remains the guarantee of record.
3. `"none"` and `"source_ip"` would both be *weaker* claims than the evidence supports,
   and neither is true.

So `"hmac"` is read here as **"authenticated by a scheme we cannot check yet"**, and the
comment in the adapter now says that rather than asserting Cartesia signs.

**Falsified by**: reading the webhook page. If it says `x-webhook-secret`, `hmac` is the
wrong label and a `shared_secret` method must be added to `WebhookAuthMethod` in the same
change that implements the check in both halves. OPERATIONS §2 gate 19(e).

## Cost — there is no per-call cost, and that is now a fact rather than a gap

* **VERIFIED-SDK** — `AgentCall` (`types/agents/agent_call.py`) has no cost, price,
  credit or currency field of any kind.
* **VERIFIED-SDK** — usage is metered at the **account** level. `cartesia-mcp`,
  `cartesia_mcp/extra_api.py:54-79`, hand-writes a call the generated clients omit:

  ```python
  client.get("/usage/credits", cast_to=dict[str, Any], options={"params": params})
  ```

  with `start_ts`, `end_ts`, `interval ∈ {day, week, month}`, `api_key_id`, and
  `group_by ∈ {capability, model, voice, api_key}` (`extra_api.py:20-21`).

`group_by` has no `call` or `agent` member, and the interval floor is a **day**. So there
is no route from a Cartesia response to a per-call rupee figure, at any granularity our
`usage_events` ledger could carry. `CartesiaEngine._cost` returning `None` is therefore
not a deferral any more — it is the correct answer, and the ledger hole it leaves is a
commercial question (a rate card, not an endpoint), not an engineering one.

## Knowledge base / documents

### Verified

* **VERIFIED-SDK** — `cartesia-ai/line`, `line/knowledge_base.py:86`:
  `GET {base_url}/agents/{agent_id}/documents/query`, query params `query`, `top_k`
  (default 5, `:14`), optional `filters` (JSON-encoded, `:82-84`); response
  `{"results": [{"content": str}, …]}` (`:121`, and `:67-71` says the pass-through is
  deliberate so new fields flow without an SDK change).
* Its auth is **not** the account API key: `Authorization: Bearer {agent_token}`
  (`knowledge_base.py:87`), where `agent_token` is *"an agent-scoped JWT minted by the
  Cartesia API at session start"* and delivered to the running agent on the websocket
  `start` message (`line/_harness_types.py:192-199`). It is a per-call credential our
  control-plane adapter never holds.
* `knowledge_base` is a shipped built-in tool of `LlmAgent`
  (`cartesia-ai/skills`, `skills/line-voice-agent/SKILL.md:323-336`), with construction-time
  `filters`, `top_k`, `timeout_s` and an `is_background` mode.

### Not verified

**No document CRUD endpoint appears in any Cartesia SDK.** `cartesia-python` and
`cartesia-js` have no documents resource at all. The only support for one is
REPORTED-DOCS: a search summary describing *"a knowledge base of documents and folders"*
in the agents platform.

So `attach_kb`/`detach_kb`/`list_kb` at `/agents/{id}/documents` remain **INFERRED** from
the sourced `/documents/query` sibling. They are unchanged, they fail loudly on a 404, and
settling them is OPERATIONS §2 gate 19(f).

`CARTESIA_CAPABILITIES.knowledge_base = True` stands: agent-scoped retrieval demonstrably
exists (the query endpoint and the built-in tool are both read at source). What is unknown
is how a document gets IN.

### Relation to our T0–T4 tiers (TRD §6)

The query endpoint is an in-call retrieval path with a 3-second default timeout
(`knowledge_base.py:15`) and a warning above 10s (`:20`), i.e. it is a **T3** engine-side
tool with zero hops from the orchestrator — the same shape as Bolna's built-in `rag_id`
KB and the reason D-33 keeps in-call retrieval on the built-in. T0 (compiled context in
the prompt) is unaffected: it rides in the prompt, which on this engine lives in the
deployed program rather than in an agent record.
