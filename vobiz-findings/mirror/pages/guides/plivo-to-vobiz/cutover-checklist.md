> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Cutover checklist

> An end-to-end runbook for moving a production Plivo voice app to Vobiz with minimal risk - swap creds, convert XML, re-point webhooks, canary traffic, then decommission Plivo.

This runbook takes you from a live Plivo voice app to running on Vobiz with the smallest possible blast radius. Work through the steps in order. Each one stays reversible until you flip production traffic, so you can pause, validate, or roll back at any point.

## Before you start

You should already have a working Plivo app in production and access to its source, environment variables, and webhook endpoints. The migration applies a small, ordered set of deltas - most of your call logic stays the same.

## The runbook

<Steps>
  <Step title="Get Vobiz credentials and start in sandbox">
    Create a Vobiz account and grab your Auth ID and Auth Token. Begin in the sandbox environment so no change you make can touch live calls until you are ready. Keep your Plivo credentials in place - you will run both side by side for a while.
  </Step>

  <Step title="Swap the client and environment variables">
    Point your code at Vobiz. If you use an SDK, change the import and client (`plivo` to `vobiz`) and rename your secrets (`PLIVO_*` to `VOBIZ_*`). If you call the API over raw HTTP, switch the base URL and send `X-Auth-ID` and `X-Auth-Token` headers. See [Auth and base URL](/docs/guides/plivo-to-vobiz/auth-and-base-url) and the full [endpoint mapping](/docs/guides/plivo-to-vobiz/endpoint-mapping).
  </Step>

  <Step title="Convert PlivoXML to VobizXML">
    Translate your call-control XML. The main change is input collection: `<GetDigits>` and `<GetInput>` become `<Gather>` with an `executionTimeout` attribute. Most other verbs map directly. The bulk-dial `<` separator is unchanged, so leave it as is. Full mapping in [XML migration](/docs/guides/plivo-to-vobiz/xml-migration).
  </Step>

  <Step title="Re-point your webhooks">
    Update the `answer_url` and `hangup_url` on your numbers and applications so call events flow to your Vobiz-aware handlers. Confirm each endpoint is reachable from Vobiz and returns valid VobizXML. See [Webhooks and signatures](/docs/guides/plivo-to-vobiz/webhooks-and-signatures).
  </Step>

  <Step title="Swap signature validation">
    Replace your Plivo request-signature check with Vobiz signature validation using the `X-Vobiz-Signature-V2` or `X-Vobiz-Signature-V3` header. Do not skip this - it is what keeps your webhooks authentic. Details in [Webhooks and signatures](/docs/guides/plivo-to-vobiz/webhooks-and-signatures).
  </Step>

  <Step title="Buy Vobiz numbers">
    **You can't port numbers from Plivo** - there is no transfer flow. Buy new Vobiz numbers from inventory, route them, and update everywhere your number is published (app, CRM, website, IVR prompts, outbound caller ID). Keep the Plivo numbers live during cutover so old callers still connect, then release them on Plivo afterwards. See [Buy a phone number](/docs/buy-a-phone-number) and [Phone numbers](/docs/guides/plivo-to-vobiz/number-porting).
  </Step>

  <Step title="Test in sandbox">
    Run your full call flows against the sandbox: inbound answer, IVR input, transfers, recordings, and hangup webhooks. Verify signature checks pass and that your XML behaves exactly as it did on Plivo before you touch live traffic.
  </Step>

  <Step title="Dual-run and canary a slice of traffic">
    Move a small percentage of real traffic - or a single low-stakes number - onto Vobiz while the rest stays on Plivo. Watch this canary slice closely for answer rate, audio quality, and webhook errors. Keep Plivo warm so you can roll back instantly.
  </Step>

  <Step title="Flip the remaining traffic">
    Once the canary is clean, move the rest of your numbers and outbound campaigns to Vobiz. Do it in batches if your volume is large so any regression stays contained.
  </Step>

  <Step title="Monitor CDRs, then decommission Plivo">
    Watch Vobiz Call Detail Records and your application logs for completed calls, failures, and cost. After a stable window with no Plivo traffic, release the old numbers and shut down the Plivo app. Review the [gotchas](/docs/guides/plivo-to-vobiz/gotchas) one last time before you close the account.
  </Step>
</Steps>

<Tip>
  Do not flip everything at once. The dual-run and canary phase is the single most effective way to de-risk this migration - it lets you compare Vobiz and Plivo on real traffic and roll back in seconds if something looks off.
</Tip>

<Note>
  A drop-in compatibility shim (`vobiz-plivo-compat` / `@vobiz/plivo-compat`) is **coming soon**. It will let most apps keep their existing Plivo-style code and switch to Vobiz with near-zero rewrite, collapsing several of the steps above. Until it ships, follow this manual runbook.
</Note>

## What's next?

<Columns cols={2}>
  <Card title="Plivo to Vobiz overview" icon="arrow-right-arrow-left" href="/docs/guides/plivo-to-vobiz">
    Back to the full migration guide and all sub-pages.
  </Card>

  <Card title="Vobiz vs Plivo" icon="scale-balanced" href="/docs/compare/vobiz-vs-plivo">
    See how the two platforms compare feature by feature.
  </Card>
</Columns>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.