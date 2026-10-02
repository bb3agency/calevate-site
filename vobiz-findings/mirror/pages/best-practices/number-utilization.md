> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Number Utilization Guide

> Maximize call connectivity, reduce spam flagging, and maintain TRAI compliance with these Vobiz number utilization best practices for Indian telephony.

## 1. Choosing the Right Number Series

Selecting the appropriate number series significantly impacts pickup rates and compliance.

### Standard High-Connectivity

* **79 Series** - Gujarat
* **80 Series** - Karnataka
* **22 Series** - Mumbai
* **11 Series** - Delhi

<Note>
  79 and 80 series numbers generally show higher connectivity because they resemble standard mobile formats and appear familiar to end users.
</Note>

### Specific Use Cases

* **BFSI Compliance** - Use **160 Series** numbers for BFSI-related services to remain compliant.
* **Promotional / Marketing** - Use **140 Series** numbers to stay within regulatory guidelines.
* **High Pickup Rate** - Consider **92 Series** numbers for improved pickup rates.

## 2. Daily Call Volume Best Practices

To prevent spam flagging and maintain number health:

* Avoid exceeding **500–600 calls** per number per day.
* Distribute calls evenly between **9:00 AM and 9:00 PM**.
* Avoid sudden traffic spikes on newly provisioned numbers.
* Do not concentrate large volumes within short time windows.

<Warning>
  **Caution:** Overstressing a number increases the likelihood of spam classification by carriers and third-party apps.
</Warning>

## 3. Warm vs Cold Calling

> "Connectivity is significantly higher when calls are warm leads with existing relationships."

<Tip>
  **Higher Connectivity Indicators**

  * Existing relationship / prior interaction
  * Call duration exceeds 1–2 minutes
  * Natural and meaningful conversations
</Tip>

<Warning>
  **Risk of Spam Detection**

  * Cold calling without opt-in
  * Repetitive dialing patterns
  * Short-duration calls ("hang-ups")
</Warning>

## 4. Number Rotation Strategy

Proactive rotation maintains "number health" and prevents burnout.

<Steps>
  <Step title="Daily Limit">
    Use a specific number once per day where possible to avoid repetitive ID patterns.
  </Step>

  <Step title="DID Rotation">
    Rotate between multiple DIDs (Direct Inward Dialing) on alternate days.
  </Step>

  <Step title="Cooling Period">
    If a number is flagged, pause usage for approximately **one week** before reattempting traffic.
  </Step>
</Steps>

## 5. Spam Recovery Best Practices

* **Pause Traffic:** Temporarily stop outbound usage on the flagged number.
* **Legitimate Use:** Use the number internally for 5–10 legitimate calls with a 3–5 minute duration.
* **Update Identity:** Refresh caller ID information in Truecaller or similar registries.
* **Gradual Reuse:** Slowly reintroduce outbound traffic to verify classification status.

## 6. Routing & Infrastructure Optimization

Vobiz uses AI-optimized routing to provide the best possible connection quality:

* Improve call connection stability
* Reduce spam exposure patterns
* Optimize network paths dynamically
* Improve delivery consistency

<Note>
  Routing optimization alone cannot compensate for high-volume abusive patterns. Responsible usage is critical.
</Note>

## 7. Key Compliance Reminders

1. Use **160 series** for BFSI communication.
2. Use **140 series** for promotional campaigns.
3. Avoid random or scraped lead databases.
4. Ensure **opt-in consent** where required.
5. Maintain controlled and predictable calling patterns.

## 8. High-Volume Warm Calling Guidelines

> "If you are running warm call campaigns (existing customers, verified opt-ins, verified prior interaction), higher daily call volumes can be supported safely."

* **Permitted Volume** - Daily volumes of **1,000 to 10,000** calls per number may be executed for verified warm leads.
* **Window Management** - Calls must be distributed evenly across the 9:00 AM – 9:00 PM window. Avoid burst dialing.
* **Sustainable Success** - Success is sustainable only when lead data is verified and recipients are familiar with your brand.
* **Natural Patterns** - Maintain meaningful call durations and natural conversation flows to signal legitimacy to carriers.

<Warning>
  **Important:** Aggressive cold dialing at high volumes may result in increased spam flagging and reduced number health. Always prioritize lead quality and opt-in status.
</Warning>

## Additional Resources

<CardGroup cols={2}>
  <Card title="Vobiz Dashboard" icon="grid" href="https://console.vobiz.ai/numbers">
    Manage Phone Numbers, Configure SIP Trunks, Billing & Balance.
  </Card>

  <Card title="Numbers API Guide" icon="phone" href="/docs/account-phone-number">
    REST API to list, purchase, and manage DID numbers.
  </Card>

  <Card title="Trunks Configuration" icon="server" href="/docs/trunks">
    Provision trunks, credentials, IP ACLs, and origination URIs.
  </Card>

  <Card title="General Best Practices" icon="star" href="/docs/best-practices">
    Security, performance, reliability, and monitoring guidance.
  </Card>
</CardGroup>

<Info>
  Sustainable call performance requires balance. Following these guidelines ensures long-term number health and maximum connection rates for your communications infrastructure.
</Info>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.