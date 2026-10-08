# DigiLocker KYC providers — comparison and recommendation (8 Oct 2026, D-692)

**Question.** Which licensed provider should run the client's DigiLocker verification of the
business owner (Aadhaar or PAN record), given the founder's rules: the client chooses
DigiLocker or document upload; the owner's ID may be Aadhaar or PAN on either path; we keep
only status, ID type, verified name, a name-match result, a masked identifier (Aadhaar last
four, PAN `XXXXX1234X`), the provider reference and timestamps; DigiLocker documents are
never stored as files.

**Method.** Each provider's PUBLIC API documentation was read on 8 Oct 2026 from the
developer workstation (the hosts that were egress-blocked from the build container on
20 Sep 2026 were reachable this time). Search-result snippets are marked as such and are
not used as wire facts.

## Summary

| | Cashfree Secure ID | Setu | Digio | IDfy |
|---|---|---|---|---|
| Public API reference readable | Yes | Yes | No (page rendered no content) | No (not found) |
| DigiLocker flow | Redirect to consent URL; URL expires 10 min after creation | Redirect to consent URL; request has `validUpto` | UNKNOWN | UNKNOWN |
| Documents | `AADHAAR`, `PAN`, `DRIVING_LICENSE` (choose per request) | Aadhaar via `/aadhaar`; other documents via `/document` (`PANCR` named; `orgId` not on the page) | UNKNOWN | UNKNOWN |
| Aadhaar number in response | Masked (`uid: xxxxxxxx5647`) | Masked (`maskedNumber: xxxx-xxxx-1234`) | UNKNOWN | UNKNOWN |
| Other personal data in the Aadhaar response | name, DOB, gender, address, photo link, XML file | name, DOB, gender, full address, photo, link to the Aadhaar XML | UNKNOWN | UNKNOWN |
| PAN via DigiLocker | Yes: `pan` (full), `name_pan_card`, `dob`, `gender`, `type` | Yes (`PANCR`), response fields not shown | UNKNOWN | UNKNOWN |
| Separate PAN verification API | Yes: `POST /pan` with `registered_name`, `name_match_score`, `name_match_result`, `pan_status` | Not checked (out of scope of the DigiLocker page) | UNKNOWN | UNKNOWN |
| Status / pull | `GET /digilocker?verification_id=` → `PENDING`/`AUTHENTICATED`/`EXPIRED`/`CONSENT_DENIED` | `GET /api/digilocker/:id/status` → `unauthenticated`/`authenticated`/`revoked` | UNKNOWN | UNKNOWN |
| Webhook | Yes; `x-webhook-signature` = base64 HMAC-SHA256 (client secret) over `x-webhook-timestamp` + raw body | **No webhook documented**; redirect carries `success`, `id`, `errCode` | UNKNOWN | UNKNOWN |
| Sandbox | `https://sandbox.cashfree.com/verification` | `https://dg-sandbox.setu.co` | UNKNOWN | UNKNOWN |
| Pricing published | Not on the docs read ("current rates are available on the Merchant Dashboard") | Not on the pages read; a search snippet says ₹4 per successful verification up to 1,000/month — REPORTED, not read on a Setu page | UNKNOWN | UNKNOWN |
| Data posture statement | "Documents are not stored on Cashfree servers after verification" (DigiLocker overview) | None on the pages read | UNKNOWN | UNKNOWN |

## Recommendation: Cashfree Secure ID

1. **Least data comes back.** We request exactly one record (Aadhaar OR PAN, the client's
   choice), and Cashfree returns the Aadhaar number already masked. Setu's Aadhaar fetch
   returns the full address, photo and a link to the Aadhaar XML for every verification —
   all of which we would receive and have to discard.
2. **A documented, verifiable webhook AND a pull.** The adapter treats the webhook as a
   doorbell and pulls the outcome with our own credentials, so a forged delivery cannot
   verify anyone; the pull is also the client's return leg.
3. **PAN on both paths.** DigiLocker PAN is supported in the same flow, and a separate
   PAN-verification API with an Income Tax Department name match exists if the manual path
   later wants an automated check of the PAN the client types (not built — see below).
4. **A stated no-storage posture** for fetched documents.

Setu is a reasonable second choice (its docs are as readable), and the adapter seam makes a
switch one file. Digio and IDfy cannot be coded against from public docs today.

## What we keep, and what we drop

- Kept: verified yes/no, ID type (`aadhaar`/`pan`), the holder name, whether it matches the
  owner the client named, the masked number, Cashfree's `verification_id`, timestamps.
- Read in memory and dropped, never logged: DOB, gender, mobile, address, photo link, XML
  link, the full PAN.
- `VerificationOutcome` refuses any `masked_id` that is not `XXXX-XXXX-dddd` or
  `XXXXXddddX`, and a `kyc_records` CHECK pins the same two shapes.

## UNKNOWN (founder / account set-up)

- ~~IP allow-listing vs `x-cf-signature`~~ — ANSWERED 8 Oct 2026: IP whitelisting is
  required in sandbox and production; `x-cf-signature` is the mutually exclusive
  alternative; 25 public IPv4 max; refusal code `ip_validation_failed`
  (https://www.cashfree.com/docs/secure-id/get-started/integration/ip-whitelisting-verification).
  We whitelist the VPS IPv4 and send no signature (gate K-2).
- Price per verification (dashboard only). OPERATIONS gate K-2.
- The value of the PAN document response's `status` field on success (the page lists the
  field without an example value); the adapter does not rely on it and requires a
  well-formed PAN and a name instead.
- Whether sandbox verification needs a real DigiLocker account (a search snippet says the
  sandbox flow needs real Aadhaar data — REPORTED, not read on a provider page).
- Cashfree's DPA / sub-processor terms and data-retention period: not read. Before
  `kyc_verification_provider` is set, Cashfree must be added to `/legal/subprocessors`
  (OPERATIONS gate K-1).

## Not built

- Cashfree `POST /pan` (PAN verification with name match) for the manual path: available,
  not wired; the reviewer compares the uploaded card against the masked PAN.
- Setu, Digio, IDfy adapters.

## Sources (read 8 Oct 2026)

- https://www.cashfree.com/docs/api-reference/vrs/v2/digilocker/create-digilocker-url
- https://www.cashfree.com/docs/api-reference/vrs/v2/digilocker/get-digilocker-verification-status
- https://www.cashfree.com/docs/api-reference/vrs/v2/digilocker/get-document-from-digilocker
- https://www.cashfree.com/docs/api-reference/vrs/v2/digilocker/webhooks-digilocker
- https://www.cashfree.com/docs/api-reference/vrs/webhook-signature-verification
- https://www.cashfree.com/docs/api-reference/vrs/v2/pan/verify-pan-sync
- https://www.cashfree.com/docs/secure-id/digilocker/digilocker
- https://docs.setu.co/data/digilocker/quickstart
- https://docs.setu.co/data/digilocker/overview
- https://documentation.digio.in/digikyc/digilocker/ (no content rendered)
- Search results only (not wire facts): Setu pricing snippet; IDfy and Digio DigiLocker
  searches returned other vendors' pages.
