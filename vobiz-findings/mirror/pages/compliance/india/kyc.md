> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# India Number KYC

> Verify your identity or business to start renting Indian phone numbers. Our verification process is fully automated and takes less than 2 minutes.

## Overview

<CardGroup cols={2}>
  <Card title="Verification Time" icon="clock">
    **\~2 Minutes** - Instant approval
  </Card>

  <Card title="Method" icon="bolt">
    **Real-time API** - Fully automated
  </Card>
</CardGroup>

## Individual Verification

Perfect for personal use, startups, or individual business owners.

| # | Document | Description |
| - | - | - |
| 1 | Aadhaar Verification | Real-time e-KYC verification |
| 2 | PAN Verification | Instant individual PAN validation |

## Company Verification

For registered businesses, partnerships, and corporations.

| # | Document | Description |
| - | - | - |
| 1 | PAN Verification | Instant company PAN validation |
| 2 | GST Verification | Real-time GSTN data lookup |

## Verification Steps

<Steps>
  <Step title="Log in to the Vobiz Console">
    Navigate to the KYC section of the [Vobiz Console](https://console.vobiz.ai/app/kyc).
  </Step>

  <Step title="Select your verification type">
    Choose **Individual** or **Company** depending on your registration.
  </Step>

  <Step title="Enter the required details">
    Provide Aadhaar/PAN for individuals, or PAN/GST for companies.
  </Step>

  <Step title="Complete verification">
    Approval is instant - typically in under 2 minutes.
  </Step>
</Steps>

<Tip>
  Ready to verify? [Get Verified Now](https://console.vobiz.ai/app/kyc) - instant approval in \~2 minutes.
</Tip>

## Verifying your customers (resellers & multi-tenant)

If you onboard your own customers under sub-accounts, each `customer_use` sub-account must complete KYC **in its own name** before it can place calls. A fresh `customer_use` sub-account is created with `kyc_calls_blocked: true` and stays blocked until verification completes.

You can run that verification programmatically rather than sending each customer to the console:

| Approach | Best for |
| - | - |
| [Per-document API](/docs/sub-accounts/kyc/overview) | Building KYC directly into your own onboarding UI - PAN, GST, CIN, or Aadhaar via DigiLocker. |
| [Hosted KYC session](/docs/sub-accounts/kyc/kyc-session) | Emailing the customer a signed Vobiz-hosted link, or redirecting them inline to the hosted widget. |

<Note>
  Document requirements follow the customer's `business_type` (individual vs. registered company). Build and test the whole flow without real documents using [KYC Test Mode](/docs/sub-accounts/kyc/test-mode).
</Note>

## Next Steps

<CardGroup cols={2}>
  <Card title="India Calling Regulations" icon="shield-check" href="/docs/compliance/india/calling-regulations">
    Regulatory requirements and compliance setup.
  </Card>

  <Card title="UCC Management" icon="shield-exclamation" href="/docs/compliance/india/ucc">
    Handle UCC complaints and avoid TRAI penalties.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.