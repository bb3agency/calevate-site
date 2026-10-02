> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# DLT Entity Registration Guide

> Step-by-step DLT registration and compliance process on Vobiz - Principal Entity, header, content template, and consent template approval for India voice and messaging.

This guide covers **registering your organisation and your content** on DLT (Distributed Ledger Technology) - Principal Entity registration, header approval, content templates, and consent templates. This is the one-time foundation every business must complete before any regulated voice or messaging traffic can go live in India. It is **not** about registering a specific phone number.

## Entity registration vs. DID provisioning

DLT has two distinct layers - you register your **organisation** once, then register **each DID number** you are provisioned.

| | This page - [DLT Entity Registration](/docs/best-practices/dlt-registration) | [DID Provisioning](/docs/best-practices/did-provisioning) |
| - | - | - |
| **What gets registered** | Your **organisation**, sender header, and message templates | A **specific DID number** (the header / Header CLI) |
| **Layer** | Entity & content layer | Per-DID layer |
| **When** | Once, at onboarding - before you have any number | Every time a new 140 / 160 DID is provisioned |
| **You end up with** | A **PE ID** and **PE Certificate**, approved header, approved templates | An approved header, carrier approval, and an allocated DID |
| **Key inputs** | PAN, COI, GST, address proof, template text | **PE Certificate**, signed **LOI**, **TM ID** / **Header CLI**, **NOC**, MOA or GST |
| **Who does it** | You, on the DLT portal | You, on your DLT portal (160 series) or against your TM ID with PE approval (140 series) |

<Tip>
  **Order of operations** - complete this page first to get your PE ID, then follow [DID Provisioning](/docs/best-practices/did-provisioning) for each 140 / 160 DID you are provisioned. For the commercial side - how numbers are sourced, LOI, and documents - see the [140 & 160 Acquisition Guide](/docs/best-practices/140-160-acquisition).
</Tip>

## 1. Overview

<CardGroup cols={2}>
  <Card title="140 - Promotional Communication" icon="bullhorn">
    Used for marketing, sales, and promotional offers. Requires strict DLT registration and opt-in consent.
  </Card>

  <Card title="160 - Transactional / Service" icon="receipt">
    Used for OTPs, alerts, updates, and transactional communication. Requires PE and Template registration.
  </Card>
</CardGroup>

### Mandatory DLT Registration

Under TRAI UCC Regulation 2018, all commercial communication must be registered on the Distributed Ledger Technology (DLT) platform. No number can be activated without:

* Principal Entity (PE) registration
* Header approval
* Content template approval
* Consent template approval (for 140)

<Info>
  Official Registration Portal: [Tata Tele DLT Portal](https://telemarketer.tatateleservices.com/#/)
</Info>

## 2. Principal Entity (PE) Registration

This is the foundational step for all businesses using commercial communication. Every organization must register as a Principal Entity.

### A. New Registration Process

<Steps>
  <Step title="Step 1">
    Visit the Official DLT Portal.
  </Step>

  <Step title="Step 2">
    Click on "Principal Entity".
  </Step>

  <Step title="Step 3">
    Click "New Registration".
  </Step>

  <Step title="Step 4">
    Select "No" when asked if already registered as PE.
  </Step>
</Steps>

### Organization & Document Requirements

**Required Details**

* Organization Name (as per PAN)
* Organization Category
* PAN Number
* Authorized Contact Person
* Address & Verified Mobile/Email

**Mandatory Documents**

* PAN Card
* Certificate of Incorporation (COI)
* GST Certificate
* Address Proof
* Business Nature Proof

<Info>
  **Approval Timeline** - Review typically takes **24 working hours**. Upon approval, you will receive your unique **Principal Entity ID (PE ID)**.
</Info>

<Tip>
  **Already Registered?** If you have a PE ID from another operator, select "Yes" during registration to map your existing ID.
</Tip>

## 3. Header Registration

A header is your approved sender identity - a 6-character alphanumeric name that represents your brand.

| Type | Used For | Notes |
| - | - | - |
| Promo Header | 140 / Marketing | Alphanumeric, first digit matches category. |
| Other Headers | 160 / Transactional | Service Implicit/Explicit messaging. |
| Rules | 6 characters | Must be exactly 6 characters and relate to your brand identity. |

### Registration Process

<Steps>
  <Step title="Login as Principal Entity" />

  <Step title="Select &#x22;New SMS Header Registration&#x22;" />

  <Step title="Choose Type (Promotional or Others)" />

  <Step title="Select Industry Category" />

  <Step title="Create & Check Availability" />

  <Step title="Add Nature of Business & Justification" />

  <Step title="Upload Support Docs (Trademark/Website)" />

  <Step title="Submit Request" />
</Steps>

## 4. Content Template Registration

All message content must be pre-approved. Selecting the correct communication type is critical for activation.

### Variables & Placeholders

Use the format `{#var#}` for dynamic content like OTPs or names.

```text Example Template theme={null}
Dear Customer, your OTP is {#var#}. Do not share this with anyone.
```

### Setup Steps

* Select Approved Header
* Select Comm Type (Promo/Transactional)
* Enter Template Name & Text
* Submit for Approval

## 5. Consent Template Registration

<Warning>
  Required for **140 Series only**.
</Warning>

Consent templates define the purpose and method of collecting customer consent for receiving promotional communications.

> "By registering, you consent to receive promotional calls regarding our services."

### Registration Fields

| Field | Example |
| - | - |
| Consent Name | `User_Reg_Consent` |
| Brand Name | `MyBrand` |
| Consent Text | Max 1000 characters... |

## 6. Final Activation Flow

### 140 Series (Promotional)

<Steps>
  <Step title="Approved PE ID" />

  <Step title="Promo Header" />

  <Step title="Promo Template" />

  <Step title="Consent Template" />

  <Step title="Provisioning" />

  <Step title="Active Traffic" />
</Steps>

### 160 Series (Transactional)

<Steps>
  <Step title="Approved PE ID" />

  <Step title="Trans. Header" />

  <Step title="Trans. Template" />

  <Step title="Provisioning" />

  <Step title="Active Traffic" />
</Steps>

## 7. Commercial & Billing Notes

| Item | Detail |
| - | - |
| Number Rental | Billed separately |
| Channel Charges | Standard rates |
| Usage | Billed per minute |

## 8. Compliance Guidelines

<Warning>
  **Strict Compliance Guidelines**

  * Communication must match approved template exactly.
  * Variables must follow registered format.
  * Misuse may result in immediate operator suspension.
</Warning>

## Need Assistance?

Our compliance team is available to guide you through the registration process for your specific brand requirements. Contact us at [support@vobiz.ai](mailto:support@vobiz.ai).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.