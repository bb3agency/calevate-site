> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Contacts

> Keep your customer list in step from a CRM — create, read, update, delete, and record consent with its source.

```http theme={null}
POST /api/v1/contacts
Authorization: Bearer ta_live_…
Content-Type: application/json
```

```json theme={null}
{
  "phone": "+91 98765 43210",
  "name": "Asha Rao",
  "email": "asha@example.com",
  "externalId": "LSQ-42",
  "tags": ["hot lead", "sky towers"],
  "language": "Hindi",
  "consent": { "status": "granted", "source": "99acres enquiry form, 17 Sep" }
}
```

```json theme={null}
{
  "id": "cust_9f2c1a44-…",
  "phone": "919876543210",
  "name": "Asha Rao",
  "email": "asha@example.com",
  "externalId": "LSQ-42",
  "tags": ["hot-lead", "sky-towers"],
  "language": "Hindi",
  "note": null,
  "consent": { "status": "granted", "source": "99acres enquiry form, 17 Sep", "recordedAt": "2026-09-17T09:40:00Z" },
  "source": "api",
  "acquiredFrom": null,
  "createdAt": "2026-09-17T09:40:00Z"
}
```

## Endpoints

| Method | Path | What |
| - | - | - |
| `GET` | `/contacts` | List, newest first. Filter with `tag`, `externalId` or `phone` |
| `POST` | `/contacts` | Create — or **update the person already on that number** |
| `GET` | `/contacts/{id}` | One contact |
| `PATCH` | `/contacts/{id}` | Change any subset of the fields |
| `DELETE` | `/contacts/{id}` | **Erase** them: the contact, their conversations and transcripts, their calls, any queued call, their campaign rows, and the recordings of their website calls and of their calls on numbers you brought |

<Warning>
  **What erasure removes from recordings.** Recordings of their **website** calls,
  and of their phone calls on **numbers you brought**, are deleted within a day,
  whatever retention they had left. Recordings of their phone calls on a number
  you **took from us** are held by the phone carrier and are **not** removed
  automatically once the contact is erased — contact support to have them
  deleted.
</Warning>

<Note>
  **A POST on a number you already have updates that person and answers
  `200`;** a new person answers `201`. A CRM that syncs the same lead twice must
  not double your list, so the number is the identity.
</Note>

## Fields

<ParamField body="phone" type="string" required>
  Required on create. E.164 with or without the `+`; spaces are fine. Normalised
  the way the importer normalises, so `+91 98765 43210` and `9876543210` are one
  person.
</ParamField>

<ParamField body="name" type="string | null">
  Up to 120 characters.
</ParamField>

<ParamField body="email" type="string | null">
  Lower-cased.
</ParamField>

<ParamField body="externalId" type="string | null">
  Your CRM's id for this person, unique in your workspace. `GET
      /contacts?externalId=` finds them by it; the same id on a second person is a
  `409`.
</ParamField>

<ParamField body="tags" type="string[]">
  Up to 20, normalised the way the console normalises them: lower case, spaces
  to hyphens. Replaces the list.
</ParamField>

<ParamField body="language" type="string | null">
  Which language to write to them in — one the console offers — or `null`.
</ParamField>

<ParamField body="note" type="string | null">
  Free text, up to 2,000 characters.
</ParamField>

<ParamField body="consent" type="object">
  `{ "status": "granted" | "withdrawn" | "unknown", "source": "…" }`.

  **`source` is required for `granted` and `withdrawn`** — where they agreed or
  refused, in a sentence. It is recorded with the time, because "where did they
  consent" is what a regulator asks and "the CRM said so" is not an answer.
  Sending a contact is not consent; only `granted` with a source is.

  A contact marked `withdrawn` is never rung, messaged or included in a
  campaign, whichever channel they said it on.
</ParamField>

## Responses

<ResponseField name="201 / 200" type="object">
  The contact. `201` for a new one, `200` for one the POST updated.
</ResponseField>

<ResponseField name="400" type="object">
  A field that does not follow the rules above.
</ResponseField>

<ResponseField name="404" type="object">
  Not one of your contacts.
</ResponseField>

<ResponseField name="409" type="object">
  Another contact already has that `externalId` (or, on a PATCH, that phone).
</ResponseField>

## Related

* [Place a call](/api-reference/place-call) — a call to a number that is not yet
  a contact creates one, with the `name` and `source` you send.
* [Report an event](/api-reference/report-event) — also creates the contact if
  needed, and can enrol them in a sequence.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.