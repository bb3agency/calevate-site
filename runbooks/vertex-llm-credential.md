# The in-call LLM bearer stopped rotating

**Alarms:** `vertex_llm_credential_refresh_failed`, `engine_credential_not_replaced`.
**Blast radius when it lands:** every in-call model turn, for every client, on every live
phone call. Vertex answers `401` and the agent goes silent mid-conversation. Nothing else
in this platform reports it — the call connects, the STT works, the TTS works, and the
agent has nothing to say.

**You have time, and that is the whole point of the alarm.** The bearer is minted with a
12-hour lifetime and replaced every 4 hours (`REFRESH_INTERVAL_HOURS`), so the credential
in the engine's store still has **at least 8 hours left** when the first page fires. Two
consecutive failed rotations still leave 4 hours of working service. This alarm is a
deadline, not an outage — treat it as one and it never becomes the other.

## 0. What actually happened

`apps/workers/vertex_credential.py::refresh_in_call_llm_credential` runs at 01:20, 05:20,
09:20, 13:20, 17:20 and 21:20 UTC. Each tick:

1. reads the service-account key (`gcp_service_account_json`, from the secrets manager),
2. mints a 1-hour JWT-bearer token (RFC 7523, `apps/workers/google_oauth.py`),
3. spends it on ONE call — `iamcredentials.googleapis.com/…:generateAccessToken` with
   `lifetime: "43200s"` — to get the long-lived one,
4. checks the **granted** expiry (never the requested one),
5. hands the bearer to the engine through `VoiceEngine.set_llm_credential`.

Nothing stores the bearer. It is not in the database, not in Redis and not on disk — it
lives in one local variable and goes to the engine. There is nothing to inspect, which is
why the log lines below are the whole evidence trail.

## 1. Which arm failed — read the `detail:` line

Every paging arm raises the SAME code, deliberately: they differ in cause, not in
consequence — each ends with the engine holding a credential nobody refreshed — and the
first three steps are identical for all of them. The alert body names the arm; the table
below is the map. (No count is written here on purpose: an arm added later would make a
number wrong and nothing would notice. `grep -c '_page(' apps/workers/vertex_credential.py`
is the answer that cannot go stale.) Find the matching log line from the same tick:

```
docker compose -p calevate -f compose.prod.yml logs --since 5h workers | grep vertex_
```

**`-p calevate -f compose.prod.yml`, always** — `runbooks/deploy-failed.md` §1 explains
why a bare `docker compose` in that directory reads the DEV file instead.

| Log line | What it means | Fix |
| --- | --- | --- |
| `vertex_bearer_no_service_account` | No `gcp_service_account_json`, or the leg is on but GCP is not configured. | Install the key in the ops console (Secrets). §2. |
| `vertex_credential_unparseable` | The key is present and is not a Google service-account JSON. | Re-download it from the GCP console; do not hand-edit it. |
| `vertex_bearer_assertion_failed` | Google refused the signed assertion. The key is revoked, or the account is deleted. | Mint a new key for the same account; the token cache drops the retired one on the first success. |
| `vertex_bearer_refused` | `generateAccessToken` returned non-200. **A 403 here almost always means the account lacks `roles/iam.serviceAccountTokenCreator` on ITSELF.** | §3. |
| `vertex_bearer_expiry_unreadable` / `vertex_bearer_malformed` | The response was not the shape Google documents. | Rare. Check Google Cloud status before anything else. |
| alert says "lasting only N minutes" | The org policy is not set, so Google capped the lifetime at 1 hour. | §4. **Nothing was installed** — the leg is still running on the previous credential. |
| alert says "already expired" | This host's clock is wrong. | Fix NTP on the host. **Nothing was installed.** |
| `vertex_credential_install_failed` | The bearer was minted fine and the ENGINE refused it. | §5. |

## 2. Is the leg even supposed to be on?

Three conditions, and the job says which one is unmet rather than reporting one "not
configured". Read them straight out of the running configuration:

```
uv run python -m scripts.check_config_applies
```

The leg is live only when `VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE` is `True` (a `Final` in
`packages/shared/src/calevate_shared/engine.py`), `gcp_project_id` is set, and the selected
engine's LLM leg is ours. A tick that logs `vertex_credential_skipped` with a `reason:` is
**not a failure** — it is a deployment that is not on this leg, and it raises no alarm.

## 3. `403` from generateAccessToken — the IAM grant

The service account calls `generateAccessToken` on **itself**. That is a real IAM grant
and it is the one people forget:

```
gcloud iam service-accounts add-iam-policy-binding <SA_EMAIL> \
    --member="serviceAccount:<SA_EMAIL>" \
    --role="roles/iam.serviceAccountTokenCreator"
```

`<SA_EMAIL>` is the `client_email` inside the key JSON. This is an **external** change —
it is nobody's to code around, and OPERATIONS §2 gate 16d owns it.

## 4. "lasting only N minutes" — the org policy

Google's default cap is 3600s. Twelve hours requires the service account to be listed in
the org policy `constraints/iam.allowServiceAccountCredentialLifetimeExtension`. Until it
is, this rotation refuses to install: a 1-hour token on a 4-hour cadence is a guaranteed
three-hour hole in every cycle, and installing it would trade a page now for silence on a
client's phone call later.

Set the policy (org admin, **external**), or — if the policy cannot be had — the cadence
must change, not the check. `MIN_GRANTED_LIFETIME_S` is derived from
`REFRESH_INTERVAL_HOURS`; move the interval and the floor moves with it.

## 5. The engine refused the credential

Two shapes, and they are different problems.

**`engine_credential_not_replaced`.** The store APPENDED the new bearer beside the old one
instead of replacing it, so the engine now holds several credentials under one name and
picks between them itself. The leg's health has stopped being a function of anything we
do. Remove the stale entries in the vendor console, then re-run the rotation. This also
answers a question nobody had answered: the vendor's `POST /providers` documents a status
enum whose only member is `added`, so replace-vs-append was never written down. If this
fires, the answer is "append", and `set_llm_credential` in `apps/api/engine/bolna.py`
needs the delete-by-id path the vendor's `DELETE /providers/{provider_key_name}` cannot
currently give it.

**`vertex_credential_install_failed`.** The vendor refused the write. The overwhelmingly
likely cause is the one marked assumption in this whole design:
`Settings.bolna_llm_credential_name` (default `CUSTOM`) is the name we write under, and
**nobody has confirmed which name the hosted platform reads `llm_key` from** for a
`provider: "custom"` leg. It is `applies: live`, so the fix is a field in the ops console
and takes effect on the next tick — no deploy, no restart, no republish. OPERATIONS §2
gate 16c is the call that settles it.

## 6. Verify the fix without waiting four hours

The job is idempotent — every tick mints a fresh bearer and overwrites — so running it by
hand is safe at any time and costs one signature and two round trips:

```
uv run python -m scripts.rotate_llm_credential
```

Exit 0 = rotated. Exit 3 = this deployment is not on that leg (see §2). Exit 1 = it tried
and failed, and the worker log names which arm.

A healthy run logs `vertex_credential_rotated` with `expires_in_s`, a `fingerprint` (12
hex characters of SHA-256, so two rotations can be told apart without the credential ever
appearing in a log) and `replaced_in_place=True`.

## 7. What this is NOT

* **Not the dashboard AI.** That is D-127, a different Vertex door
  (`…:generateContent`), and it mints its own 1-hour token per request. It is unaffected.
* **Not the post-call extraction.** That stays on Sarvam permanently
  (`GEMINI_EXTRACTION_DEFAULT is False`) because it reads the raw transcript.
* **Not fixable with an API key.** A Vertex API key forces the GLOBAL endpoint — Google's
  own guidance is "Don't use the global endpoint if you have ML processing requirements,
  because you can't control or know which region your ML processing requests are sent to"
  — so it would move Indian callers' words out of India. Same for Bolna's native
  `provider: "google"`, which is the AI Studio Developer API and has no region pinning at
  all. Both are recorded as rejected with their reasons (D-405, D-407); neither is a
  shortcut available during an incident.
