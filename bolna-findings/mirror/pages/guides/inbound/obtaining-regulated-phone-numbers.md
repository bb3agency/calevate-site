> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# How to Get 140 & 160-Series Phone Numbers in India

> Complete guide to obtaining regulated 140-series and 160-series phone numbers in India for Voice AI calling. Covers DLT registration, required documents, KYC, and the step-by-step provisioning process.

## Why Do You Need Regulated Numbers?

To make commercial or telemarketing calls in India, businesses must use regulated phone numbers issued under TRAI guidelines. These numbers require registration on the **DLT (Distributed Ledger Technology)** platform before they can be used.

| Number Series  | Use Case                                                   | Telephony Provider |
| -------------- | ---------------------------------------------------------- | ------------------ |
| **140-series** | Telemarketing and promotional calls                        | Vobiz              |
| **160-series** | Transactional and service calls (banking, insurance, etc.) | Plivo              |

<Note>
  DLT registration is mandatory to procure 140 or 160-series numbers from Indian telephony providers.
</Note>

***

## 140-Series Numbers (Telemarketing)

140-series numbers are used for **promotional and telemarketing calls**. Bolna uses **Vobiz** as the telephony provider for Indian calling, and Vobiz recommends registering on the **TATA Teleservices DLT portal**.

### Registration Process

<Steps>
  <Step title="Register as Principal Entity on DLT">
    Visit the [TATA Teleservices DLT portal](https://telemarketer.tatateleservices.com/#/) and select **Register as Principal Entity**.
  </Step>

  <Step title="Complete Digital KYC">
    Upload the following documents during registration:

    | Document                          | Details                                                                |
    | --------------------------------- | ---------------------------------------------------------------------- |
    | **Certificate of Incorporation**  | Issued by Ministry of Corporate Affairs (MCA) / Registrar of Companies |
    | **GST Certificate**               | Copy of your GST registration                                          |
    | **Company PAN Card**              | PAN card in the company's name                                         |
    | **Director List & MOA**           | Memorandum of Association with the list of directors                   |
    | **Letter of Authorization (LOA)** | Signed by the director whose name is mentioned in the MOA              |

    <Note>
      The LOA must be signed by a director whose name appears in the Memorandum of Association (MOA). Download the sample LOA template from the DLT portal, fill in the required details, and get it signed before uploading.
    </Note>
  </Step>

  <Step title="Submit Letter of Authorization (LOA)">
    Submit the LOA with your official **mobile number** and **email ID**. OTPs for verification will be sent to these details during the registration process. Contact [compliance@bolna.ai](mailto:compliance@bolna.ai) to solicit a sample LOA.

    <Warning>
      The mobile number and email ID in the LOA become your permanent registered contact for all DLT communications. These cannot be easily changed after submission — choose carefully.
    </Warning>
  </Step>

  <Step title="Complete Payment">
    Once your Digital KYC is verified, a payment link for **₹5,900** will be generated on the portal. Complete the payment to finalize your Principal Entity registration.

    <Note>
      Keep the mobile number and email from your LOA accessible throughout the process — all OTPs are sent there.
    </Note>
  </Step>
</Steps>

***

## 160-Series Numbers (Transactional & Service Calls)

160-series numbers are used for **transactional and service communication** such as banking alerts, insurance reminders, and regulatory notifications. These require additional provisioning through **Plivo** after DLT registration.

### Documents Required

<CardGroup cols={2}>
  <Card title="RBI / SEBI Certificate" icon="file-certificate">
    Required as proof of regulatory compliance during Header registration on DLT
  </Card>

  <Card title="Certificate of Incorporation & GST" icon="building">
    COI and GST Certificate for Plivo KYC verification
  </Card>

  <Card title="PE & TM IDs" icon="id-card">
    Principal Entity ID and Telemarketer ID, generated after DLT registration
  </Card>

  <Card title="Compliance Application Name" icon="file-shield">
    Your compliance name to be shared with Plivo during provisioning
  </Card>
</CardGroup>

### Provisioning Process

<Steps>
  <Step title="Register on the DLT Portal">
    Complete your DLT registration as a Principal Entity (same process as the 140-series registration above). This generates your **PE ID** and **TM ID**.
  </Step>

  <Step title="Submit KYC to Plivo">
    Share your **Certificate of Incorporation (COI)** and **GST Certificate** with Bolna for Plivo KYC verification.

    <Tip>
      This step can be skipped if your Plivo KYC on Bolna is already completed.
    </Tip>
  </Step>

  <Step title="Share your PE & TM-ID with Bolna">
    Provide your **PE-ID**, **TM-ID**, and **compliance application name** to Bolna for verification with Plivo.
  </Step>

  <Step title="Plivo Allocates the 160-Series Number">
    Plivo will verify the submitted details and allocate the 160-series number to your Plivo KYC previously done on your Bolna account.

    <Warning>
      The allocated numbers will **not be active** at this stage. Further steps are required before you can start making calls.
    </Warning>
  </Step>

  <Step title="Complete Header Registration on DLT">
    Register your Header on the DLT portal. Submit the **RBI / SEBI Certificate** as proof of regulatory compliance during this step.
  </Step>

  <Step title="Obtain URN & Share with Bolna">
    After Header registration, obtain your **URN (Unique Reference Number)**. Share the URN and the **approval screenshot** with Bolna. Bolna will ensure Plivo coordinates with TATA Teleservices for header approval.
  </Step>

  <Step title="Complete Template Registration on DLT">
    Once the header is approved, proceed with **Template registration** on the DLT portal.
  </Step>

  <Step title="Numbers Become Active">
    Once the template is approved, your 160-series numbers will be **active** and ready for calling.
  </Step>
</Steps>

***

## Next Steps

Once your DLT registration is approved and numbers are provisioned, you can:

<CardGroup cols={2}>
  <Card title="Buy Phone Numbers" icon="phone" href="/docs/guides/inbound/buying-phone-numbers">
    Purchase regulated numbers for your outbound agents
  </Card>

  <Card title="Make Outgoing Calls" icon="phone-arrow-up-right" href="/docs/guides/outbound/making-outgoing-calls">
    Set up your outbound calling agent
  </Card>

  <Card title="Batch Calling" icon="file-spreadsheet" href="/docs/guides/outbound/batch-calling">
    Run calling campaigns at scale
  </Card>

  <Card title="Calling Guardrails" icon="shield-check" href="/docs/guides/outbound/calling-guardrails">
    Stay compliant with TRAI regulations
  </Card>
</CardGroup>
