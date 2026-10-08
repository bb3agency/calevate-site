# KYC review and the no-cold-calls pledge (D-692)

Outbound calling needs, on every plan, a verified KYC record and an accepted, current
no-cold-calls pledge. Inbound is never affected. This runbook is for the operator who
reviews a client's documents or is asked why a client cannot dial.

## A client cannot place outbound calls

The refusal names the rule. In order of the dial gate:

| Rule | What it means | What to do |
|---|---|---|
| `kyc_missing` | Nothing verified yet | Point the client to **Verify your business**. |
| `kyc_not_verified` | Submitted, in review, rejected or expired | Submitted/in review: decide it (below). Rejected: the client fixes what the reason names and resubmits. |
| `kyc_digilocker_required` | An operator required DigiLocker and no run has completed since | The client completes DigiLocker on Verify your business, or an operator clears the requirement. |
| `outbound_pledge_missing` / `outbound_pledge_outdated` | No acceptance, or one of an older version | The account owner accepts it on Verify your business. An operator cannot accept for them. |

## Reviewing documents

1. Admin console → **KYC reviews** lists records waiting, oldest first, with the path and
   the owner-ID type (Aadhaar or PAN).
2. Open the client → **KYC**. The review card shows the declared details, the masked owner
   ID, the DigiLocker name match where there is one, and the pledge state.
3. **Open** each file (decrypted for you; the view is audited). Check:
   - the business certificate matches the legal name, and is the GST certificate when the
     business says it is GST-registered;
   - the owner ID's name matches the owner named, and its visible digits match the masked
     number on record;
   - an Aadhaar is the **masked** copy (only the last four digits visible). Reject an
     unmasked one; it cannot be detected automatically.
4. **Approve** (for an incorporation or Udyam certificate, type the CIN, LLPIN or Udyam
   number you checked; a GST certificate uses the GSTIN on record) or **Reject** with a
   reason the client will read.
5. Either decision deletes the owner-ID file. Open it before deciding.

An owner-ID file nobody decides on is deleted after 30 days by the nightly purge; the alarm
`kyc_owner_id_purge_abandoned` means that purge failed (see `runbooks/alarm-index.md`).

## Requiring DigiLocker ("deeper verification")

On the client's **KYC** page, **Require DigiLocker** with a reason. Outbound pauses at once
for that client until a DigiLocker run completes after that moment; inbound continues.
**Stop requiring DigiLocker** lifts it. Both are audited.

## DigiLocker shows "not available yet"

No provider credentials are installed. Gates K-1 and K-2 (`docs/OPERATIONS.md`): Cashfree on
the public sub-processor list first, then `kyc_verification_provider`,
`kyc_verification_client_id` and `kyc_verification_client_secret` in the ops console. The
manual path works meanwhile.
