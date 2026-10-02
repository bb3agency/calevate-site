> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# UCC & NDNC Compliance

> NDNC/DND registry, UCC complaints, and TRAI enforcement for Indian voice numbers - how Vobiz enforces the Do Not Call list and what to do when a complaint arrives.

## What is NDNC / DND?

The **National Do Not Call (NDNC)** registry - also known as the **Do Not Disturb (DND)** registry - is maintained by TRAI. Subscribers on this list have opted out of receiving unsolicited commercial calls. Calling a registered subscriber without valid prior consent is a violation of TRAI's TCCCPR Regulations, 2025, and results in a **UCC (Unsolicited Commercial Communication)** complaint against your account.

<Note>
  NDNC and UCC are two sides of the same framework. NDNC is the registry (who has opted out); UCC is the complaint mechanism (what happens when you call them anyway).
</Note>

## Number series and NDNC scope

NDNC compliance applies to all outbound commercial calls on Indian number series:

| Number series | Type | NDNC applies |
| - | - | - |
| `140xxxxx` | Promotional / transactional voice | Yes |
| `160xxxxx` | Service / informational voice | Yes |
| Standard 10-digit mobile/landline | Direct calls | Yes |
| `1800xxxxx` | Toll-free inbound | Inbound only - N/A |

<Warning>
  **Number series matter.** Using the wrong series is itself a violation. Complaints arising from calls made via incorrect number types are treated as UCC regardless of consent documentation.
</Warning>

<Note>
  OTP delivery and service alerts with documented prior consent are classified as **transactional** and face lower restrictions, but consent records are still required.
</Note>

## How Vobiz enforces NDNC

Vobiz integrates NDNC scrubbing into the outbound call path for Indian numbers:

1. **Checks numbers against the NDNC registry** before allowing promotional or transactional calls on regulated series
2. **Blocks calls** to registered DND numbers that lack documented consent
3. **Logs blocked attempts** for compliance review

## Staying compliant - proactive steps

<Steps>
  <Step title="Scrub your contact list before campaigns">
    Remove any numbers on the NDNC registry that lack documented consent before you start dialling.
  </Step>

  <Step title="Maintain consent records">
    For each number you call, keep a record of the consent date, the channel used, and the consent text shown to the subscriber. Consent must be no older than 6 months.
  </Step>

  <Step title="Honour opt-out requests immediately">
    When a subscriber asks to stop receiving calls, remove them from your active list instantly and do not redial. Calling after an opt-out is a UCC violation regardless of prior consent.
  </Step>

  <Step title="Use the correct number series">
    Promotional calls must use the `140` series. Transactional and service calls use `160`. Using a standard mobile number for commercial outreach is itself a violation.
  </Step>
</Steps>

## UCC notifications

If Vobiz receives a UCC complaint traced to a number on your account, you will be notified on this timeline:

| Time | Stage | Trigger |
| - | - | - |
| 0 Hours | Initial Notification | Vobiz receives and validates UCC complaint |
| 6 Hours | Reminder | No valid proof submitted yet |
| 12 Hours | Final Reminder | Last chance before compliance action |
| 24 Hours | Compliance Action | Proof deadline expired - compliance ID blocked |

All UCC notifications are sent from `ndnc@vobiz.ai` to the designated compliance contacts on your account.

<Warning>
  Not receiving an email notification does not exempt you from compliance obligations. Keep your contact details updated in the Vobiz Console.
</Warning>

## Action required within 24 hours

### 1. Submit consent proof

Proof must cover the last 6 months and include:

* **Business Logo** to verify identity on DLT
* **Date of Consent** within last 6 months
* **Complainant Phone Number** exactly as reported

### 2. Remove the complainant

Remove the complainant's number from your calling list immediately. Continuing to call someone who has filed a UCC complaint is a major violation, even if you hold valid consent.

## Consequences & enforcement

| Scenario | Trigger | Consequence |
| - | - | - |
| Single Complaint | No proof submitted in 24 hours | Compliance ID blocked |
| First Violation | 5+ unique complaints within 10 days | Compliance ID suspended for 15 days |
| Second Violation | Repeated 5+ complaints after 1st violation | **TRAI Blacklisting (1 Year)** |

## TRAI blacklisting

<Warning>
  If blacklisted by TRAI, the following actions are taken across **all operators in India** (not just Vobiz):

  * Immediate disconnection of all telecom resources (PRI/SIP Trunks)
  * Blacklisted on the national DLT platform for 1 year
  * Prohibited from obtaining any new telecom services in India
  * Possible blocking of devices used for making UCC calls
</Warning>

## Related

<CardGroup cols={2}>
  <Card title="India Calling Regulations" icon="shield-check" href="/docs/compliance/india/calling-regulations">
    Regulatory requirements and compliance setup.
  </Card>

  <Card title="India Number KYC" icon="id-card" href="/docs/compliance/india/kyc">
    Verify your identity to start renting Indian numbers.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.