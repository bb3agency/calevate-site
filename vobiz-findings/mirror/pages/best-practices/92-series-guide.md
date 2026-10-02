> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# 92 Series Number Guide

> Acquire and manage 92-series mobile-format numbers on Vobiz for India - higher consumer pickup rates, mandatory per-number Aadhaar (KYC) verification, and the 5-per-person limit.

92-series numbers are **mobile-format** Indian numbers. Because they present to the recipient like a regular mobile number rather than a landline or short-code, they typically achieve **higher pickup rates for consumer outbound** - making them a strong choice for lead generation, collections, and customer engagement dialing.

<Info>
  **Requesting access:** 92-series numbers are provisioned on request. Email [support@vobiz.ai](mailto:support@vobiz.ai) with your account ID, use case, and how many numbers you need to start provisioning.
</Info>

## 1. Overview

<CardGroup cols={2}>
  <Card title="Why 92-series" icon="mobile">
    * **Mobile-format** presentation to the callee
    * **Higher pickup rates** vs landline / short-code formats
    * Ideal for consumer outbound - lead gen, collections, engagement
  </Card>

  <Card title="What's required" icon="id-card">
    * **Aadhaar (KYC) verification per number**
    * **Max 5 numbers per person** (per KYC identity)
    * Provisioned on request via support
  </Card>
</CardGroup>

## 2. Requirements & limits

92-series numbers are **Aadhaar-bound**, so two rules always apply:

* **Aadhaar (KYC) verification for every number.** Each 92-series number you acquire must be verified against an Aadhaar identity - there is no bulk shortcut; every number is individually bound to a verified Aadhaar.
* **Maximum 5 per person.** A single person (one KYC / Aadhaar identity) can hold **at most 5** 92-series numbers.

<Note>
  You can provision **as many 92-series numbers as you need overall** - they simply have to be spread across **separate KYC-verified identities**, with no more than 5 numbers under any one identity.
</Note>

## 3. Aadhaar verification (per number)

Verification is completed through the **DigiLocker Aadhaar flow**, which binds each 92-series number to the verified Aadhaar:

1. **Initiate** the DigiLocker OAuth flow - see [DigiLocker Initiate](/docs/sub-accounts/kyc/digilocker-initiate).
2. The number holder completes Aadhaar consent in DigiLocker.
3. **Verify** and bind the number - see [DigiLocker Verify](/docs/sub-accounts/kyc/digilocker-verify). Pass the target number as `linked_number` to bind the Aadhaar to that specific 92-series number.

Repeat this for **each** 92-series number (up to 5 per identity).

## 4. How to acquire

<Steps>
  <Step title="Request the numbers">
    Email [support@vobiz.ai](mailto:support@vobiz.ai) with your account ID, use case, and the quantity of 92-series numbers you need.
  </Step>

  <Step title="Complete Aadhaar KYC per number">
    Run the [DigiLocker Aadhaar flow](/docs/sub-accounts/kyc/digilocker-verify) for each number, binding it via `linked_number`. Remember the **5-per-identity** cap - use additional KYC identities for larger volumes.
  </Step>

  <Step title="Go live">
    Once verified and assigned, the numbers are ready for outbound dialing on your account.
  </Step>
</Steps>

## 5. Support & Contact

| Purpose | Contact |
| - | - |
| 92-series provisioning, KYC, quantity requests | [support@vobiz.ai](mailto:support@vobiz.ai) |
| Technical integration, SIP, API setup | [support@vobiz.ai](mailto:support@vobiz.ai) |
| Enterprise accounts & escalations | Your dedicated Vobiz account manager |

<Note>
  See also the [140, 160 & 92 series FAQ](/docs/faq/number-series) for a quick overview of Vobiz's Indian number series.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.