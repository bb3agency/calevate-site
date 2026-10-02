> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# DID Provisioning Process for 140 & 160 Series

> Client onboarding guide for provisioning 140 and 160 series DID numbers on Vobiz - PE certificate, LOI, TM ID header registration, NOC-based DLT registration, channels, lock-in, and timelines.

Vobiz provisions two categories of **DID (Direct Inward Dialing) numbers** for **outbound voice calling only** - the **140 series** and the **160 series**. Both are provided against a fixed timeline, a common set of mandatory documents, and a minimum channel allocation. The end-to-end registration workflow differs between the two series and is detailed below.

<Warning>
  **Outbound only.** Neither 140 nor 160 DIDs are enabled for receiving inbound calls. If you need inbound, Vobiz provides standard DID numbers that can be paired with your 140 / 160 setup.
</Warning>

## 1. Key Requirements at a Glance

| Parameter | 140 Series DID | 160 Series DID |
| - | - | - |
| **Timeline** | 1 week from initiation | 1 week from initiation |
| **Mandatory documents** | PE (Principal Entity) Certificate - TATA or Airtel, plus an LOI (Letter of Intent) signed by the Principal Entity | PE (Principal Entity) Certificate - TATA or Airtel, plus an LOI (Letter of Intent) signed by the Principal Entity |
| **Minimum channels** | 30 channels per DID | 30 channels per DID |
| **Lock-in period** | 12 months | 12 months |
| **Registration route** | DLT header registration via your **TM ID** | **NOC**-based DLT header registration |
| **Direction** | Outbound only | Outbound only |

<Info>
  **PE Certificate and LOI are client-arranged prerequisites.** The **PE (Principal Entity) Certificate** must be obtained from either **TATA Teleservices** or **Airtel**, and an **LOI (Letter of Intent)** must be signed by the Principal Entity. Both are mandatory for procuring either a 140 or a 160 DID and should be arranged **before** initiating the process. Both series also carry a **12-month lock-in period** from the date of allocation.
</Info>

## 2. Terminology

The DLT portal and the carrier use specific terms. This is what each one means in the context of your provisioning request.

| Term | Full form | What it means for you |
| - | - | - |
| **DID** | Direct Inward Dialing number | The actual phone number being provisioned - your 140 or 160 number |
| **PE** | Principal Entity | Your **organisation** as registered on the DLT platform. Identified by a **PE ID** |
| **PE Certificate** | Principal Entity Certificate | Proof of your DLT entity registration, issued by **TATA** or **Airtel**. Mandatory |
| **LOI** | Letter of Intent | A document signed by the Principal Entity authorising Vobiz to procure the DID on your behalf. Mandatory |
| **TM ID** | Telemarketer ID | The telemarketer identifier under which the header is registered on DLT |
| **Header** | Header / Header CLI | On voice, the header **is the DID number** itself - the identity presented on outbound calls |
| **NOC** | No Objection Certificate | Issued by Vobiz, confirming the header is being provided specifically to your Principal Entity. Used in the 160 route |
| **MOA** | Memorandum of Association | Company document establishing your nature of business. GST certificate is accepted as an alternative |
| **Channels** | Concurrent call channels | Simultaneous outbound calls the DID can carry. Minimum **30 per DID** |
| **Carrier** | TATA / Airtel | The telecom operator that gives final approval before the DID is allocated |

## 3. Process for 140 DID

The 140 series follows a **DLT header registration route via your Telemarketer (TM) ID**.

<Steps>
  <Step title="Principal Entity signs the LOI">
    The **Principal Entity (PE)** signs an **LOI (Letter of Intent)** authorising procurement of the 140 DID. This is mandatory before the number can be procured.
  </Step>

  <Step title="Register the header on the DLT portal">
    The header - that is, the **DID number** - is registered on the DLT portal using your **Telemarketer (TM) ID**.
  </Step>

  <Step title="Principal Entity approves the header">
    The **Principal Entity** reviews and approves the header registration from their side.
  </Step>

  <Step title="Carrier approval">
    Once PE approval is confirmed, the header is submitted for approval at the **carrier (TATA / Airtel)** end.
  </Step>

  <Step title="DID allocated to your Vobiz account">
    Once **both** the PE approval and the carrier approval are complete, the 140 DID is allocated to your Vobiz account.
  </Step>

  <Step title="Start outbound calling">
    You can now begin making outbound calls using the allocated 140 number.
  </Step>
</Steps>

### Activation flow - 140

`Sign LOI → Register header via TM ID → PE approves → Carrier approves → DID allocated → Outbound calling`

## 4. Process for 160 DID

The 160 series follows an **NOC-based DLT registration route**. You file the registration yourself on your own DLT portal, using an NOC issued by Vobiz.

<Steps>
  <Step title="Principal Entity signs the LOI">
    The **Principal Entity (PE)** signs an **LOI (Letter of Intent)** authorising procurement of the 160 DID. This is mandatory before the number can be procured.
  </Step>

  <Step title="Vobiz issues the NOC">
    Vobiz issues an **NOC (No Objection Certificate)** confirming that the header - the DID number - is being provided specifically to your Principal Entity.
  </Step>

  <Step title="Register the header on your DLT portal">
    Log in to **your own DLT portal** and register the header, uploading the **NOC** provided by Vobiz.
  </Step>

  <Step title="Upload your company document">
    Upload your company's **MOA (Memorandum of Association)** or **GST certificate** to establish the nature of your business.
  </Step>

  <Step title="File under the 'Voice' category">
    The registration must be filed under the **Voice** category, since the header will be used for voice calling.
  </Step>

  <Step title="DID allocated to your Vobiz account">
    Once the DLT registration and approvals are complete, the 160 DID is allocated to your Vobiz account and outbound calling can begin.
  </Step>
</Steps>

### Activation flow - 160

`Sign LOI → Vobiz issues NOC → Register header + upload NOC → Upload MOA / GST → File under Voice → DID allocated → Outbound calling`

### Portal walkthrough - registering the header

The exact sequence inside the DLT portal for Step 3 above.

<Steps>
  <Step title="Log in to your PE Registration Portal">
    Use your registered Principal Entity credentials.
  </Step>

  <Step title="Open the Voice Header column">
    On the top menu row, locate the **Voice Header** column (2nd column) and click it. This is what files the registration under the **Voice** category.
  </Step>

  <Step title="Select &#x22;Voice Header Registration by PE&#x22;">
    Choose **Voice Header Registration by PE** from the options shown.
  </Step>

  <Step title="Enter the TM ID">
    Enter the **TM ID** (Telemarketer ID). This is provided in the NOC shared with you.
  </Step>

  <Step title="Enter the Header CLI">
    Enter the **Header CLI** - the DID number itself. This is also provided in the NOC.
  </Step>

  <Step title="Set the use case">
    In the **Use Case / Remarks** field, enter **Transactional** for 160 numbers.
  </Step>

  <Step title="Upload your company proof">
    Upload your **MOA** or **GST certificate**, whichever reflects your business category.
  </Step>

  <Step title="Complete the remarks field">
    In the next remarks field, enter **Approved**.
  </Step>

  <Step title="Upload the NOC">
    Upload the **NOC** issued by Vobiz.
  </Step>

  <Step title="Submit">
    Click **Submit** to file the registration.
  </Step>

  <Step title="Share the Application / URL Number with Vobiz">
    An **Application / URL Number** is generated on submission. Screenshot it and share it with the Vobiz onboarding team so carrier approval can be coordinated.
  </Step>
</Steps>

### Field reference

| Portal field | What to enter | Where it comes from |
| - | - | - |
| TM ID | Your Telemarketer ID | NOC issued by Vobiz |
| Header CLI | The 160 DID number | NOC issued by Vobiz |
| Use Case / Remarks | `Transactional` | Fixed value for 160 |
| Company proof | MOA or GST certificate | Your company records |
| Remarks | `Approved` | Fixed value |
| NOC | The NOC document | Issued by Vobiz |
| Category | Voice | Registered via the **Voice Header** menu |

## 5. Which Route Applies to You

| | 140 Series | 160 Series |
| - | - | - |
| **Route** | TM ID header registration | NOC-based registration |
| **Who files on the DLT portal** | Filed against your TM ID; **PE approves** | **You file** on your own DLT portal |
| **NOC required** | No | **Yes** - issued by Vobiz |
| **MOA / GST upload** | Not part of this route | **Required** |
| **Carrier approval step** | Explicit - after PE approval | Part of the DLT approval cycle |
| **Typical use** | Promotional and commercial calling | Transactional and service calling |

## 6. How This Differs from DLT Entity Registration

DLT has two distinct layers. This page is the **per-number** layer - it assumes your **organisation** is already registered.

| | [DLT Entity Registration](/docs/best-practices/dlt-registration) | This page - DID Provisioning |
| - | - | - |
| **What gets registered** | Your **organisation**, sender header, and message templates | A **specific DID number** |
| **When** | Once, at onboarding - before you have any number | Every time a new 140 / 160 DID is provisioned |
| **You end up with** | A **PE ID** and PE Certificate, approved templates | An approved header and an allocated DID |
| **Prerequisite for** | Everything below it | Outbound calling on that number |

<Tip>
  For the commercial side - how numbers are sourced, acquisition scenarios, and CPS / concurrency - see the [140 & 160 Acquisition Guide](/docs/best-practices/140-160-acquisition).
</Tip>

## 7. Support

<Warning>
  **Reminder** - both 140 and 160 DIDs are strictly for **outbound calling**. They cannot be used to receive inbound calls.
</Warning>

For questions on document formats, LOI or NOC issuance, or DLT portal registration support, contact the Vobiz onboarding team at [support@vobiz.ai](mailto:support@vobiz.ai).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.