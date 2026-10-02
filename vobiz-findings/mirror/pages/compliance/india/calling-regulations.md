> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# India Calling Regulations

> Regulatory requirements, eligibility rules, and compliance setup for domestic voice calling within India on Vobiz - DLT, KYC, and TRAI guidelines.

## Overview

These are the regulatory requirements for making and receiving voice calls within India. The rules are governed by TRAI and DoT.

<Info>
  Ready to verify your business? [Submit KYC](https://console.vobiz.ai/app/kyc) on the Vobiz Console.
</Info>

## Eligibility

Only businesses registered in India can:

* Rent Indian phone numbers
* Make domestic calls within India
* Use India domestic routes

<Warning>
  **International Businesses:** If your business is outside India, you must use international routes. This means calls are placed at international rates and display a US or international Caller ID - not an Indian number.
</Warning>

## Requirements

| Requirement | Details |
| - | - |
| Business registration | India-registered businesses only |
| KYC compliance | Required before renting Indian numbers (submit KYC) |
| Caller ID | Must use Vobiz-rented Indian phone number |
| Media anchoring | Both call legs must stay within India |

## Media Anchoring Rule

Both legs of a call must originate and terminate within India. Violating this causes calls to fail with `violates_media_anchoring` hangup cause.

### Compliant Call Architecture

| Type | Requirement |
| - | - |
| Inbound | India to India |
| Outbound | Indian number to India destination |
| Conference | All participants must be in India |

## Number Series Regulations

TRAI mandates specific number series for specific call types. Using the wrong series is itself a regulatory violation.

| Number Series | Permitted Use | Status |
| - | - | - |
| `91 series` | Standard mobile series for personal and business use | Available |
| `140 series` | Promotional voice calls only | Available |
| `Landline series` | Service and transactional calls only. Promotional content prohibited. | Available |
| `160 series` | Service and transactional calls - BFSI sector only | Available |
| `Branded ID` | Display your business name and logo on the receiver's screen | Available |

## Consent & UCC

Cold calling is prohibited in India. You need explicit digital consent before making commercial calls, and must comply with TRAI guidelines.

<Warning>
  **Unsolicited Commercial Communication (UCC)**

  Calls made without valid consent are treated as UCC. High complaint rates can lead to account suspension or blacklisting by TRAI.

  See [UCC Management](/docs/compliance/india/ucc) for enforcement details.
</Warning>

## Account Setup for India

If you need both India and international calling, you have two options:

<CardGroup cols={2}>
  <Card title="Separate Accounts" icon="user-plus">
    Create two separate Vobiz accounts with different email addresses for India vs International routing.
  </Card>

  <Card title="India Data Region" icon="globe">
    Sign up specifically for an India data region Vobiz account to access domestic number inventory.
  </Card>
</CardGroup>

## Next Steps

<CardGroup cols={2}>
  <Card title="India Number KYC" icon="id-card" href="/docs/compliance/india/kyc">
    Verify your identity or business to start renting Indian numbers.
  </Card>

  <Card title="UCC Management" icon="shield-exclamation" href="/docs/compliance/india/ucc">
    Handle UCC complaints and avoid TRAI penalties.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.