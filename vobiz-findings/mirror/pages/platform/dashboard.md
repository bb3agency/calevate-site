> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Dashboard

> A tour of the Vobiz Console dashboard - KPI cards, usage and cost charts, inbound vs outbound activity, API credentials, capacity limits, and the global call distribution map.

The Dashboard is the first screen you see after signing in. It's the single‑page snapshot of your account: how many calls you've placed, what you've spent, how much capacity you have left, and where to find the credentials your code needs.

```text URL theme={null}
https://console.vobiz.ai/app/dashboard
```

<Frame caption="Vobiz Console - Dashboard">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/auth/dashboard_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=e7e60f80d6a5398149823832856df73f" alt="Vobiz dashboard showing KPI tiles (Calls Made, Total Spend, Success Rate, SIP Trunk Calls, Voice API Calls, Active Numbers), Usage Overview and Cost Analysis line charts, Inbound vs Outbound bar chart, and Account & Infrastructure section with API credentials, global call distribution, and capacity limits" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="8000" height="4408" data-path="images/platform/auth/dashboard_blur.png" />
</Frame>

The page is laid out top‑to‑bottom in five bands. The rest of this page walks each band, left‑to‑right.

## 1. Top bar

The fixed bar at the very top of every console page.

| Element | What it does |
| - | - |
| **Vobiz logo + plan badge** (`POSTPAID` / `PREPAID`) | Click the logo to return to the dashboard from anywhere. The badge shows your current billing mode - see [Billing model](/docs/concepts/callbacks) to switch. |
| **Search Endpoints…** (⌘K / Ctrl+K) | Global search across pages, numbers, trunks, and applications. Hit `⌘K` (Mac) or `Ctrl+K` (Windows / Linux) from any screen. |
| **Date range** (`May 1, 2026 – May 30, 2026`) | Drives every chart and KPI tile on the page. Click to pick a different window - last 7 days, last 30 days, this month, custom range. |
| **BALANCE** | Wallet balance in INR. Click to open the [Transactions](/docs/platform/dashboard#transactions) view and top up. |
| **Profile menu** (avatar) | Switch sub‑accounts, manage API keys, change password, sign out. |

## 2. KPI tiles

Six tiles summarising the date range you picked. Every tile shows the **current period** value plus a **trend pill** comparing it to the previous period of the same length.

| Tile | What it measures | Action |
| - | - | - |
| **Calls Made** | Total call attempts in the range. | Click the tile to deep‑link into [CDRs](/docs/cdr) filtered to this window. |
| **Total Spend** | Sum of all charges (voice + numbers + features) in INR. The eye icon toggles the value's visibility - useful when sharing your screen. | Click to open [Transactions](/docs/platform/dashboard#transactions). |
| **Success Rate** | `connected / total attempts` for the range, expressed as a percentage. | – |
| **SIP Trunk Calls** | Calls placed through your SIP trunks. Includes the **View call logs** link → [SIP Call Logs](/docs/cdr). | View logs. |
| **Voice API Calls** | Calls placed via the REST API and XML applications. Includes **View call logs** → [Voice Call Logs](/docs/cdr). | View logs. |
| **Active Numbers** | Phone numbers currently rented on your account. | Click to open [Phone Numbers](/docs/account-phone-number). |

The trend pill colours:

* **Green ↑** - value increased vs the previous period.
* **Red ↓** - value decreased.
* **Grey "No change"** - same as previous period.

<Note>
  The pill compares **like‑for‑like windows**. A 30‑day current period is compared to the 30 days immediately before it.
</Note>

## 3. Usage & cost charts

Two side‑by‑side line charts that animate when you change the date range.

### Usage Overview

Plots three series per day:

* **Total Calls** (green) - every connected call.
* **SIP Trunk** (purple) - the subset routed through trunks.
* **Voice API** (orange) - the subset via REST / XML.

Hover any day to see the exact counts in a tooltip. Click a legend entry to hide/show that series.

### Cost Analysis

Breaks your spend down by line item per day:

| Series | What it includes |
| - | - |
| **CDR** | Voice minutes (the bulk of most accounts). |
| **NCC** | Network connection charge (per‑call surcharge where applicable). |
| **Recording** | Storage + retrieval of call recordings. |
| **Stream CDR** | Audio streaming time over WebSockets. |
| **Transcription** | STT / ASR usage during `<Gather>` and stream sessions. |
| **DID Purchase** | One‑time number purchase fees. |
| **DID Rental** | Monthly number rental. |
| **Feature Cost** | Add‑ons like premium routing, CNAM lookups, etc. |

<Tip>
  A red spike in **Stream CDR** with no matching spike in **CDR** usually means a long‑lived WebSocket stream wasn't closed when the call ended. Audit your stream `stop` handling - see [Stream events](/docs/xml/stream/stream-events).
</Tip>

## 4. Inbound & Outbound Calls

A daily bar chart with two stacked series:

* **Inbound** (green) - calls received on your numbers.
* **Outbound** (orange) - calls placed from your account.

The `Activity by date` label at the top‑right is the only legend; click either colour swatch at the bottom to filter the chart to that direction alone.

<Tip>
  If you expected outbound traffic but see only green bars, your last campaign likely didn't run. Check [Voice Call Logs](/docs/cdr) for the date and look for `ERROR` rows.
</Tip>

## 5. Account & Infrastructure

The bottom section groups everything you need to integrate with the API into three cards.

### API Credentials

| Field | What it is | Use it for |
| - | - | - |
| **Auth ID** (e.g. `MA_ZRTEMCF7`) | Your account identifier. Public - safe to include in URLs and logs. | The `X-Auth-ID` header on every API request, and the partner API. |
| **Auth Token** | Your secret. Click the eye icon (👁) to reveal, the copy icon (⧉) to copy. **Treat this like a password.** | The `X-Auth-Token` header on every API request. |

<Warning>
  Never paste the **Auth Token** into client‑side code, public repos, or screenshots. If it leaks, rotate it immediately from **Profile menu → API Keys**.
</Warning>

### Global Call Distribution

The world map shows where calls originated and terminated in the selected date range. Darker regions = more traffic. Hover any country to see the per‑country call count and spend.

Useful for spotting:

* **Unexpected geographies** - a sudden cluster in a country you don't serve usually means a misconfigured campaign or fraud. Cross‑check in [CDRs](/docs/cdr) and block the country in your dialler if needed.
* **Regulatory hot spots** - heavy India traffic? Make sure you're current on [DLT registration](/docs/best-practices/dlt-registration) and [KYC](/docs/compliance/india/kyc).

### Capacity limits

Two side‑by‑side counters showing how much call capacity your account is provisioned for.

| Counter | What it means |
| - | - |
| **CPS** (Calls Per Second) | The peak rate at which Vobiz will accept new call attempts from you. `base` is included in your plan; `purchased` is the add‑on you bought; `Total` is the sum and the actual cap. |
| **Concurrent calls** | The maximum number of calls that can be in progress simultaneously on your account. Same `base + purchased = Total` math. |

<Tip>
  Plan your campaigns against **Total**, not **base**. If a dialler attempts more than `Total` CPS, the extra attempts get a `429 Too Many Requests` response - see [Error 429](/docs/faq/error-429).
</Tip>

Need more capacity? Use the [CPS & Cost Calculator](/docs/resources/calculator) to size what you need, then ping [support@vobiz.ai](mailto:support@vobiz.ai) to provision.

## Left sidebar

The vertical icon strip on the far left is the primary navigation. From top to bottom:

| Icon | Section | What you do there |
| - | - | - |
| Gauge | **Dashboard** | You're here. |
| Phone | **Call Management** | Active calls, queued calls, live transfers. |
| Cloud | **SIP** | Trunks, credentials, IP ACLs, origination URIs. |
| ID card | **Numbers / DID** | Rent and manage phone numbers. |
| Speech bubble | **XML Applications** | Build and assign programmable call flows. |
| Receipt | **Billing** | Top‑ups, invoices, transactions. |
| Headset | **Recordings** | Browse and download call recordings. |
| Person | **Sub‑Accounts** | Manage child accounts under a parent. |
| Book (bottom) | **Docs** | Opens vobiz.ai/docs in a new tab. |
| Sun (bottom) | **Theme** | Toggle light/dark mode. |
| Door (bottom) | **Sign out** | Log out and return to the [Login](/docs/platform/login) screen. |

## Tips

* **Bookmark `console.vobiz.ai/app/dashboard`.** It's the fastest way back if you get lost in nested settings.
* **Pin the date range** to "Last 7 days" in your head - almost every triage starts there before you zoom out.
* **Watch the BALANCE pill.** Postpaid accounts can run negative briefly, but prepaid accounts will hard‑stop calls at ₹0. Set up auto‑recharge in **Billing** to avoid surprises.

## What's next

<CardGroup cols={2}>
  <Card title="Quick Start" icon="rocket" href="/docs/quick-start">
    Make your first call in under 5 minutes using these credentials.
  </Card>

  <Card title="Vobiz API Reference" icon="terminal" href="/docs/api-reference">
    Drop the Auth ID and Auth Token straight into the live API explorer.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.