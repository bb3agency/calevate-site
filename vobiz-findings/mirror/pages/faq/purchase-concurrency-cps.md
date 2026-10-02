> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Can I purchase additional Concurrency or CPS?

> Upgrade your Vobiz concurrency and CPS limits through the dashboard to scale outbound campaigns and handle thousands of simultaneous calls - step-by-step instructions.

**Yes.** Once your account has completed regulatory verification, your base provisioning limits provide a stable starting baseline. As your call volume grows, you will likely need to increase your operational capacity.

## How to request an upgrade

Vobiz provides dynamic scaling for both concurrent channels and CPS limits to support thousands of concurrent calls.

<Steps>
  <Step title="Sign in to the dashboard">
    Log into the **Vobiz Dashboard**.
  </Step>

  <Step title="Open Limits & Quotas">
    Navigate to **Settings** and select the **Limits & Quotas** tab to view your current capacities.
  </Step>

  <Step title="Confirm billing setup">
    Ensure you have sufficient prepaid balance or a post-paid billing arrangement in place. Limit modifications may require a nominal recurring or one-time provisioning fee depending on the requested volume.
  </Step>

  <Step title="Request an increase">
    Click the **Request Increase** button, specify whether you need higher Concurrency or CPS (or both), and our network team will provision it.
  </Step>
</Steps>

## Purchase through the API

For programmatic capacity upgrades:

1. [Preview the monthly price](/docs/account/channel-pricing-preview) for the required CPS or concurrent-call quantity.
2. Show the returned amount and currency to the customer for confirmation.
3. [Create the capacity subscription](/docs/account/channel-subscriptions).

The purchase API immediately debits the first month's charge and creates an active subscription that renews every 30 days. The account's assigned pricing tier controls the price, allowed quantities, and block-size rules.

<Note>
  **Enterprise Scaling** - For extremely high-volume dialers requiring multi-thousand channels or more than 10 CPS consistently, please [contact our enterprise support team](/docs/faq/contact-support) directly to establish dedicated SIP trunks and specialized routing geometries.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.