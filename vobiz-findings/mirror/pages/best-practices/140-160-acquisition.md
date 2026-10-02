> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# 140 & 160 Series Number Acquisition Guide

> Acquire TRAI-regulated 140 and 160 series numbers on Vobiz - covers eligibility, required documents, use-case scenarios, and 2025 compliance guidelines.

This guide covers the three acquisition paths for 140 and 160 series numbers on the Vobiz platform. Each path assumes you complete (or are already registered for) the underlying DLT steps - see [DLT Entity Registration](/docs/best-practices/dlt-registration) for the Principal Entity, header, and template approval process referenced below. For the per-number registration workflow - PE Certificate, LOI, TM ID and NOC routes - see the [DID Provisioning Process](/docs/best-practices/did-provisioning).

<Warning>
  **Outbound only.** Neither 140 nor 160 numbers support inbound calls. For inbound, Vobiz provides DID numbers that can be paired with your 140 / 160 setup.
</Warning>

## 1. Overview

Key differences between the two series at a glance.

<CardGroup cols={2}>
  <Card title="140 - Promotional & Commercial" icon="bullhorn">
    * Calling hours: **9 AM – 9 PM only**
    * DND bypass: **Not allowed**
    * Use: Sales, lead gen, campaigns
    * Source: **Vobiz pool** (assigned to you)
    * DLT: **TATA DLT - mandatory**
  </Card>

  <Card title="160 - Transactional & Service" icon="receipt">
    * Calling hours: **24 × 7**
    * DND bypass: **Allowed** for pre-consented transactions
    * Use: OTP, alerts, booking confirmations
    * Source: **Acquired from operator** (2 scenarios)
    * DLT: TATA DLT (Scenario 2) / any DLT as private entity (Scenario 1)
  </Card>
</CardGroup>

### Three Acquisition Paths

| # | Path | Description |
| - | - | - |
| 01 | 140 Series | Vobiz assigns from pool |
| 02 | 160 - Scenario 1 | You acquire; Vobiz delivers |
| 03 | 160 - Scenario 2 | Vobiz acquires on your behalf |

## 2. 140 Series - Vobiz Assigns from Pool

Vobiz assigns a number from its existing pool directly to your TATA DLT ID.

<Info>
  **Pre-requisite** - You must be registered on **TATA DLT specifically** - no other DLT provider is accepted. If not yet registered, Vobiz will guide you through TATA DLT registration before proceeding.
</Info>

### Step-by-Step Process

<Steps>
  <Step title="Share Your TATA DLT ID with Vobiz">
    Provide your registered TATA DLT Entity ID to the Vobiz team. This is the identifier under which the 140 number will be assigned.
  </Step>

  <Step title="Sign the Letter of Intent (LOI)">
    Vobiz issues an LOI. Review and sign it. This formalizes the number acquisition request.
  </Step>

  <Step title="Submit Required Documents">
    Upload your GST certificate, Certificate of Incorporation, and Authorised Signatory KYC documents to Vobiz.
  </Step>

  <Step title="Vobiz Assigns the Number to Your DLT ID">
    Vobiz assigns a 140 number from its existing pool to your TATA DLT ID on the DLT platform.
  </Step>

  <Step title="You Approve the Number on Your DLT Platform">
    Log into your TATA DLT account and approve the number that Vobiz has assigned to you.
  </Step>

  <Step title="Telecom Operator Approves">
    The telecom operator reviews and approves the number assignment once both parties have confirmed.
  </Step>

  <Step title="Add Your Communication Template on DLT">
    Create and submit your communication template on the TATA DLT platform. This defines the type of calls you will be making.
  </Step>

  <Step title="Template Approved - Number is Live">
    Once the telecom operator approves the template, your 140 number is active and ready to use on the Vobiz platform.
  </Step>
</Steps>

### Activation Flow

`Share DLT ID → Sign LOI → Submit Docs → Vobiz Assigns → You Approve → Operator OK → Add Template → Live`

### Documents Required

* TATA DLT Entity ID (must be pre-registered)
* Signed Letter of Intent (LOI format provided by Vobiz)
* GST Registration Certificate
* Certificate of Incorporation
* Authorised Signatory KYC (Aadhaar or Passport)

## 3. 160 Series - Scenario 1: You Acquire, Vobiz Delivers

You request the number from any operator. Vobiz provides the technical details and delivers the number.

<Info>
  **Pre-requisite** - You must be registered as a **Private Entity on the DLT platform** before proceeding with this scenario.
</Info>

### Step-by-Step Process

<Steps>
  <Step title="Technical Discussion with Vobiz - First">
    Before requesting the number from any operator, engage Vobiz to agree on: the data centre where the 160 number will be delivered, the protocol to be used, and any technical constraints. This agreement must be in place before the number is requested.
  </Step>

  <Step title="You Request the Number from Your Operator">
    Approach any telecom operator of your choice and request a 160 series number. Mention that the number will be routed through Vobiz infrastructure.
  </Step>

  <Step title="Operator Requests Technical Details from Vobiz">
    The operator will ask for Vobiz's technical information - specifically the IP address and the data centre where the 160 number should be delivered. Vobiz provides this directly to the operator.
  </Step>

  <Step title="You Assign the Number to Vobiz's DLT ID">
    Once the operator has set up the number, assign it to Vobiz's DLT ID (shared by Vobiz with you). This is done on your DLT platform.
  </Step>

  <Step title="Vobiz Approves the Number">
    Vobiz reviews and approves the number assignment on their DLT platform.
  </Step>

  <Step title="Add Your Communication Template on DLT">
    Create and submit your communication template on your DLT platform.
  </Step>

  <Step title="Vobiz Tests the Number">
    Vobiz runs end-to-end tests to confirm the 160 number is routing correctly, audio quality is acceptable, and the integration is working as agreed.
  </Step>

  <Step title="Number is Live">
    Once tests pass, you can start using the 160 number on the Vobiz platform.
  </Step>
</Steps>

### Activation Flow - Scenario 1

`Tech Discuss → Request No. → Operator ↔ Vobiz → Assign DLT → Vobiz Approves → Add Template → Testing → Live`

### Documents Required

* DLT Private Entity registration (mandatory prerequisite)
* Technical agreement with Vobiz (data centre, protocol - agreed before number request)
* Vobiz DLT ID (shared by Vobiz - needed to assign the number)

## 4. 160 Series - Scenario 2: Vobiz Acquires on Your Behalf

Vobiz requests the number from the operator for you. You provide documents and approve on TATA DLT.

<Info>
  **Pre-requisite** - You must have a **TATA DLT ID specifically**. No other DLT provider is accepted for this scenario. If you are not registered on TATA DLT, Vobiz will guide you through registration first.
</Info>

### Step-by-Step Process

<Steps>
  <Step title="Sign the Letter of Intent (LOI)">
    Vobiz shares the LOI format with you. Review, sign, and confirm the number of channels and quantity of 160 numbers required. This kicks off the acquisition.
  </Step>

  <Step title="Submit Required Documents">
    Provide your GST certificate, PAN, Authorised Signatory KYC details, and your TATA DLT ID to Vobiz.
  </Step>

  <Step title="Vobiz Acquires the Number from the Operator">
    Using the documents and authorisation you provided, Vobiz requests the 160 number(s) from the telecom operator on your behalf.
  </Step>

  <Step title="Operator Assigns Number to Your TATA DLT ID">
    The telecom operator allocates the number and assigns it to your TATA DLT ID on the DLT platform.
  </Step>

  <Step title="You Approve on Your TATA DLT Platform">
    Log into your TATA DLT account and approve the number that has been assigned to your entity.
  </Step>

  <Step title="You Assign the Number to Vobiz's DLT ID">
    On your TATA DLT platform, assign the approved number to Vobiz's DLT ID (provided by Vobiz).
  </Step>

  <Step title="Vobiz Approves - Operator Gives Final Approval">
    Vobiz approves the assignment on their DLT platform. The telecom operator then gives its final approval to complete the process.
  </Step>

  <Step title="You Create a Communication Template on DLT">
    Create and submit your communication template on the TATA DLT platform. This defines the nature of calls being made.
  </Step>

  <Step title="Vobiz Tests the Number">
    Vobiz runs end-to-end tests to confirm the 160 number is working correctly across all agreed parameters.
  </Step>

  <Step title="Number is Live">
    Once tests pass, you can start using the 160 number on the Vobiz platform.
  </Step>
</Steps>

### Activation Flow - Scenario 2

`Sign LOI → Submit Docs → Vobiz Acquires → Operator Assigns → You Approve → Assign to Vobiz → Final Approval → Add Template → Testing → Live`

### Documents Required

* Signed Letter of Intent - channels and quantity confirmed (LOI format from Vobiz)
* GST Registration Certificate
* PAN Card
* Authorised Signatory KYC details
* TATA DLT ID (must be TATA DLT specifically)
* Vobiz DLT ID (shared by Vobiz - needed to assign the number in Step 6)

## 5. CPS & Concurrency

<Warning>
  **140 / 160 CPS and concurrency are separate from your central pool.** Calls on 140 and 160 series numbers do **not** draw from your account's central CPS / concurrency allocation - they use their own dedicated capacity, which is **purchased separately and provisioned on request**.
</Warning>

To increase the CPS or concurrency available to your 140 / 160 numbers, email [support@vobiz.ai](mailto:support@vobiz.ai) with your account ID and the target CPS / concurrency, and the team will provision the dedicated 140 / 160 capacity for you. This is separate from your standard account limits - for the central pool, see [Can I purchase additional Concurrency or CPS?](/docs/faq/purchase-concurrency-cps).

## 6. Support & Contact

| Purpose | Contact |
| - | - |
| General queries, document submission, onboarding | [support@vobiz.in](mailto:support@vobiz.in) |
| Technical integration, SIP, API setup | [support@vobiz.in](mailto:support@vobiz.in) |
| Enterprise accounts & escalations | Your dedicated Vobiz account manager |

<Info>
  Ready to get started? Our team will guide you through the right acquisition path for your business. Contact [support@vobiz.in](mailto:support@vobiz.in) or visit [www.vobiz.in](https://www.vobiz.in).
</Info>

<Note>
  This document is for informational purposes only. TRAI regulations are subject to change. Always verify current requirements at [trai.gov.in](https://trai.gov.in).
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.