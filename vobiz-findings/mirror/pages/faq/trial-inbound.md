> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Can I connect my trial number for inbound calls?

> Vobiz trial numbers are outbound-only - understand why inbound routing is restricted on trial accounts and the exact steps to unlock it on a verified account.

**No.** Trial numbers cannot be used for inbound call connectivity. Incoming routing is available only on active, fully provisioned numbers on a verified account.

## Why are inbound calls blocked on trials?

To comply with telecom regulations and prevent abuse, trial numbers are sandboxed. They are provided so developers can test outbound API connectivity, WebRTC signaling, Voice XML execution, and webhooks in a controlled environment. Opening inbound routing to unverified accounts would expose the network to potential toll fraud and routing manipulation.

## How to unlock inbound calling

If you have successfully tested your application for outbound and are ready to map incoming calls to your `SIP URI` or webhook URLs, you must upgrade your account:

<Steps>
  <Step title="Open your dashboard">
    Navigate to your Vobiz Dashboard.
  </Step>

  <Step title="Complete KYC verification">
    Complete the **KYC Verification** process (GST for organizations, Aadhaar/PAN for individuals).
  </Step>

  <Step title="Add a payment method">
    Add a payment method and purchase a dedicated incoming trunk or DID.
  </Step>

  <Step title="Configure routing">
    Configure your newly provisioned number to point to your Voice XML application.
  </Step>
</Steps>

<Info>
  **Developer Tip:** While you cannot receive external carrier calls on trial numbers, you can simulate inbound webhooks and test your backend application logic by directly hitting your server's endpoints using tools like Postman or curl with our standard JSON payload format.
</Info>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.