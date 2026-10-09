# KYC review and the no-cold-calls pledge (D-692, D-696)

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
   the owner-ID type (PAN on a document review; Aadhaar or PAN through DigiLocker).
2. Open the client → **KYC**. The review card shows the declared details, the masked owner
   ID, the DigiLocker name match where there is one, and the pledge state.
3. **Open** each file (decrypted for you; the view is audited). Check:
   - the business certificate matches the legal name, and is the GST certificate when the
     business says it is GST-registered;
   - the owner ID is a **PAN card**, its name matches the owner named, and its digits
     match the masked PAN on record (`XXXXX1234X`).
4. **Check the PAN at Income Tax** (the review card links it):
   1. Open https://eportal.incometax.gov.in/iec/foservices/#/pre-login/verifyYourPAN.
   2. Enter the PAN, the full name and the date of birth exactly as printed on the card,
      and your own mobile number. Type the OTP it sends.
   3. It answers whether the details match the PAN database. One mobile number can check
      at most 5 PANs a day; past that, wait until tomorrow or use another reviewer.
   4. Do not write the date of birth down anywhere: in a ticket, a note or the reason.
5. **Approve** only if it said the details match: tick **PAN details matched at Income
   Tax** (approving a document review is refused without it; the tick is stored with your
   name and the time, and in the audit log), and for an incorporation or Udyam certificate
   type the CIN, LLPIN or Udyam number you checked (a GST certificate uses the GSTIN on
   record). If anything does not match, **Reject** with a reason the client will read,
   naming the detail (for example "The name on the PAN card does not match the owner
   name you gave"), never the date of birth.
6. Either decision deletes the owner-ID file. Open it before deciding.

**An Aadhaar copy is never accepted on a document review** (D-696, Aadhaar regs 2021
reg. 16C(1): an Aadhaar may not be accepted as proof of identity without verifying UIDAI's
signature, which we do not do). The upload and the submit refuse one. Submissions still waiting
with an Aadhaar copy when D-696 shipped were returned to the client asking for the PAN card,
and their files deleted; reviews already decided stand. A client who wants to use Aadhaar
verifies through DigiLocker once it is available.

An owner-ID file nobody decides on is deleted after 30 days by the nightly purge; the alarm
`kyc_owner_id_purge_abandoned` means that purge failed (see `runbooks/alarm-index.md`).

## Requiring DigiLocker ("deeper verification")

On the client's **KYC** page, **Require DigiLocker** with a reason. Outbound pauses at once
for that client until a DigiLocker run completes after that moment; inbound continues.
**Stop requiring DigiLocker** lifts it. Both are audited.

## DigiLocker shows "not available yet"

No provider is configured. Cashfree refused us on 9 Oct 2026 (sole proprietorship); Setu,
Sandbox, Surepass and Digio are being asked. Gates K-1 and K-2 (`docs/OPERATIONS.md`): the
chosen provider on the public sub-processor list first, then `kyc_verification_provider`,
`kyc_verification_client_id` and `kyc_verification_client_secret` in the ops console. The
manual path (owner's PAN card) works meanwhile.
