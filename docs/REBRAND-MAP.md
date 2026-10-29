# Rename map: Calevate → new name, and the new Udyam registration

Prepared 29 Oct 2026 at commit `1746978e` (tag `checkpoint-pre-rename-2026-10-29`). Counts are
`git grep -i calevate` over the tracked tree on that commit. Nothing here has been changed
yet; this is the map to work from once the name and the registration details are known.

**The size of it:** 7,774 occurrences in 1,632 files, 590 distinct internal names. The work
splits into four kinds, each changed differently (§2).

**Pre-launch (founder, 29 Oct 2026): nothing is live and nothing has been signed with anyone,**
so everything is renamed, internal names included. Renaming them now is a one-off with test
data only; after launch each one carries the production risks listed in §2C.

**The detail lives beside this file, in `docs/rebrand/`:**

| File | What it holds |
|---|---|
| `INVENTORY.md` + `inventory.tsv` | every occurrence, file and line, by kind and area; every distinct internal name; every image. Regenerate with `scripts/rebrand_inventory.sh` on the day |
| `VISIBLE-TEXT-AND-LEGAL.md` | every string a person reads, every image with the name in it, every legal clause and field |
| `DATA-AND-INTEGRATIONS.md` | names stored in the database, Redis and storage, and names sent to or created at outside services |
| `INFRA-DEPLOY-ENV.md` | build, deploy, CI, the VPS and the local machine, with a cutover runbook |

---

## 1. What Umesh gives me first

| # | Detail | Where it ends up |
|---|---|---|
| 1 | **New product name**, exactly as written (e.g. capitals) | every screen, email, legal page, invoice, logo alt text |
| 2 | **Enterprise name on the new Udyam certificate** (may differ from the product name) | `LEGAL_ENTITY_NAME` in `apps/web/src/lib/legal/placeholders.ts`, invoices |
| 3 | **Udyam number**, registration date, enterprise type, NIC code | `ENTITY_REGISTRATION_NUMBER` (today `UDYAM-AP-04-0146106`) |
| 4 | **Legal form** of the new enterprise (still a sole proprietorship, or a company/LLP/partnership?) | `apps/api/billing/gst.py:85` says "a sole proprietorship"; Terms; the contract-change question in §4 |
| 5 | **City and state** to publish (city only, never the street — 4 Sep 2026 rule) | `REGISTERED_ADDRESS`, `JURISDICTION_CITY` |
| 6 | **GST status** under the new enterprise | `GST_STATUS`; `GST_SUPPLIER_*` settings if registered |
| 7 | **New domain** | ~38 code files today, then one setting (§2B) |
| 8 | **Mailboxes** on the new domain: support, security, alerts, ops (today `support@`, `security@`, `alerts@`, `ops@calevate.tech`) | config, legal pages, email sender |
| 9 | **Contact phone and grievance officer**, if they change | `CONTACT_PHONE`, grievance page |
| 10 | **Logo files**: full logo with tagline, without tagline, icon only (PNG, transparent), and the tagline text | replace `apps/web/public/brand/calevate-*.png` and `icon.png` |

Before choosing: check the domain is free and do a trademark search on the name in classes 9
and 42 (software and SaaS) at ipindia.gov.in. A name you have to drop after the switch costs
the whole exercise twice.

---

## 2. What I change in the repository

### A. Everything a client or a caller sees (must change)

| Area | Size | Notes |
|---|---|---|
| Screens: client dashboard, admin console, signup, status page, marketing home | "Calevate" 560× in 155 files under `apps/web/src` | page titles in `apps/web/src/app/layout.tsx`, nav, empty states, Pip's name stays "Pip" |
| Logos and favicon | 4 files in `apps/web/public/brand/` | new artwork from Umesh |
| Emails: every message the platform sends | inventory and proposed wording in `docs/EMAILS.md` (D-933) | the name is `apps/api/core/brand.PRODUCT` and the domain `apps/api/core/console_links.DOMAIN`; `tests/email_brand_guard_test.py` refuses either written into an email module. Senders are per purpose (`notifications_from` plus `sender_security`, `sender_billing`, `sender_alerts`, `sender_operator`), all falling back to `notifications_from` until set |
| Invoices | `apps/api/billing/gst.py`, `invoice.py` | supplier name, registration, the "sole proprietorship below the threshold" sentence (`gst.py:85`) |
| Legal pages: Terms, Privacy, DPA, Acceptable use, Sub-processors, Refunds, Grievance, Cookies | `apps/web/src/lib/legal/*.ts` + `placeholders.ts` values | a **material** revision of every blocking document (§4) |
| WhatsApp templates submitted into each client's own WhatsApp account | `apps/api/whatsapp/templates.py`: names `calevate_booking_confirmed`, `calevate_details_you_asked_for`, `calevate_payment_link`, `calevate_call_back_time` | new names mean Meta re-approves them in every connected account; the old ones keep working meanwhile |
| Text we send to the voice platform that a person may read | `apps/api/engine/thinnest_customer_data.py:54` do-not-call reason "Calevate do-not-call list" | |
| What agents SAY on calls | **two lines** | `TRIAL_LINE_MESSAGE` (`apps/api/campaigns/engine_numbers.py:710-713`) is spoken to anyone who rings the shared trial number back and names the brand: the trial-line agent must be republished after the change. The maintenance prompt (`apps/workers/maintenance.py:256`) names "the Calevate platform" to the model, which could repeat it. Nothing else: the prompt layers, notices, spoken style and call script carry the client's business name only (D-679) |

### B. The domain (must change, and I make it one setting first)

`calevate.tech` appears 506× in 169 files. Hosts in use: `app.`, `admin.`, `api.`, `hooks.`,
`status.`, `www.`. About 20 web files and 18 api/worker files hard-code it (sign-in pages, console
links, cookie and CSP code, health and healer pages, TLS expiry check, payments, webhook
receivers, the ops catalogue). **First step:** move every one of those to a single
`ROOT_DOMAIN`-style setting, so the domain change itself becomes one value, and so the old and
the new domain can both be served during the switch. nginx already takes `ROOT_DOMAIN`
(`infra/nginx/calevate.conf.template`).

### C. Internal names nobody outside sees (recommend: keep, change later or never)

| Name | Size | Cost of renaming |
|---|---|---|
| Python package `calevate_shared` / `calevate-shared` | 1,486× in 729 files | mechanical, but touches almost every file and every import |
| Database `calevate`, role `calevate_app` | 157× in 63 files | production database rename + every connection string; downtime |
| Server account `calevate`, `/var/www/calevate`, `/etc/calevate`, `/opt/calevate-python`, `/var/backups/calevate` | 35 + 18 + 2 + 4 files | moving the deploy root, sudoers, systemd units, backups; done by hand on the VPS |
| systemd units `calevate-*.service/.timer` | 52× in 15 files | reinstall on the VPS |
| Docker compose project `calevate`, image `calevate/app` | 17 files | recreates containers; volumes are named after the project, so careless renaming loses Redis data |
| Environment variables `CALEVATE_*` (14 names) | 82× in 27 files | `.env` edits on the VPS |
| Sign-in cookies `__Host-calevate_admin_session`, `_client_session`, `_google_signin` | 4 names | **renaming signs every user out once** |
| Browser storage keys `calevate.*` / `calevate:*` | 9 keys | users lose small remembered choices once |
| Redis keys and job names `calevate:*` | many | in-flight jobs and locks keyed by name |
| Keys we put on every call at the voice platform: `calevate_call_id`, `calevate_lead_id`, `calevate_forwarding_leg`, idempotency prefixes `calevate-call-`, `calevate-customer-`, `calevate-fwd-` (`engine/thinnest.py:2761,2771,3395,3405`, `thinnest_customers.py:203`) | — | the three metadata keys are written and never read back (calls match on `reference`), so they rename freely; the **idempotency prefixes** can double-place a call or double-rent a number if a retry crosses the deploy, so drain retries first |
| Cryptographic labels: password pepper, emailed-code key, OTP/email-token/session hash domains, caller-memory key (`authn/hashing.py:153`, `authn/codes.py:74`, `otp.py:76`, `tokens.py:79`, `sessions.py:151`, `compliance/caller_ref.py:102`) | — | **NEVER rename.** Every stored password, invite and session stops matching, and caller memory is orphaned beyond the reach of erasure. Details in `docs/rebrand/DATA-AND-INTEGRATIONS.md` |
| R2 bucket names `calevate-call-recordings`, `calevate-db-backups` | settings + docs | a bucket cannot be renamed; it means a new bucket and copying every recording |
| GitHub repository name | — | GitHub redirects the old URL; update the VPS `git remote` |

None of these is visible to a client or a caller. **Decision: rename them too, before launch**
(founder, 29 Oct 2026, "literally from everywhere"; nothing is live). The right-hand column is
then the list of things to do carefully rather than reasons to skip: sign-outs and lost browser
choices only touch test users; the database, server account, paths, units and Docker volumes
are renamed in one maintenance window with a `pg_dump` first; R2 buckets are new buckets with
the few test objects copied; voice-platform keys are renamed once no test call is in flight.

Two internal names reach people and must change regardless:
- **The password rule refuses the brand as a password** (`calevate2026!`,
  `apps/api/authn/policy.py:144,219`); it must refuse the new name instead.
- **The reply-to and published mailbox `calevate.voice@gmail.com`**
  (`config.py:1353` `notifications_reply_to`, `placeholders.ts:223`): a new mailbox under the
  new name.

### D. Docs and tests

- Docs: 1,653 mentions in 149 files under `docs/`, 236 in `runbooks/`, plus `CLAUDE.md`,
  `docs/AGENTS.md`, `README.md`. Rewritten to the new name; `docs/evidence/` and dated vendor
  correspondence stay as written, since they are records of what was true then.
- Tests: 1,068 mentions in 436 files; they follow whatever the code does.

---

## 3. What Umesh changes by hand outside the repository

| Service | What to change |
|---|---|
| **Domain registrar** | buy the new domain. **Keep `calevate.tech` registered for at least 12 months**: sent emails, invoices, clients' bookmarks, OAuth and webhook registrations all point at it, and it redirects to the new one |
| **Cloudflare** | add the new zone; DNS for `app`, `admin`, `api`, `hooks`, `status`, `www` and the root, proxied; a new origin certificate; copy the security rules; turn the old zone into redirects once the switch is done |
| **VPS (Hostinger)** | new TLS paths and `ROOT_DOMAIN` exports for the deploy; `.env` values that hold the domain (`NEXT_PUBLIC_API_BASE_URL` and similar); hostname optional |
| **Email (Resend)** | add and verify the new domain (SPF, DKIM, DMARC); the backup alert file `/etc/calevate/alerts.env` too |
| **Mailboxes** | create support, security, alerts, ops on the new domain; forward the old addresses for a year |
| **Our admin console settings** | `notifications_from`, `webhook_base_url` (→ `hooks.<new domain>`), the Google, Zoho and HubSpot redirect URIs |
| **ThinnestAI** | the webhook address follows `webhook_base_url`; tell Ashutosh the new name and entity; their DPA and invoices in the new entity's name |
| **Razorpay** | business name, KYC under the new Udyam entity (a new legal entity usually means a new account or a formal entity change with them), checkout name and logo, webhook URL, settlement bank account in the new name |
| **Bank** | current account in the new enterprise name (Udyam is usually one of the two proofs the bank asks for) |
| **Google Cloud** | OAuth consent screen: app name, logo, authorised domains, redirect URIs for Calendar and Google sign-in; verify the new domain in Search Console; a changed app name can trigger Google's re-verification |
| **Meta** | Business Manager business name and business verification with the new entity's documents; app name; WhatsApp display name (Meta approves it); webhook callback URL and Embedded Signup domains |
| **Zoho, HubSpot** | app name and redirect URIs |
| **Cashfree (DigiLocker)**, if it is switched on | entity KYC |
| **Azure, Google (Gemini), Sarvam, Cartesia** | organisation and billing name, so their invoices name the new entity |
| **Sentry, Healthchecks.io** | project and check names; allowed domains in Sentry |
| **GitHub** | rename the repository if wanted; then `git remote set-url` on the VPS |
| **Udyam portal** | the new registration itself |

---

## 4. The legal side of changing the entity

- **Nothing is signed and nobody is live (29 Oct 2026),** so there is no contract to transfer
  and no client to re-ask. The documents are revised in place to the new entity before launch.
  The test accounts that accepted earlier versions simply accept the new version, which the
  product already asks for (a material revision).
- **The documents name the supplier, its Udyam number, its city and its GST position;** the
  Terms' courts and arbitration clause names the city. All of it changes with the entity.
- **Have the lawyer read the revised set once** before launch, since the entity is the party
  every promise is made by.
- **Invoices**: none issued to a real client yet, so the new entity starts the only series.
- **GST**: confirm the status for the new enterprise before the first invoice.
- **Sub-processors**: no company changes, so no 30-day notice is owed for the rename itself.
- **Data**: the processing does not change, but the controller-side contact details in the
  Privacy notice and the Grievance page change with the entity.

---

## 5. Order of the switch

1. Choose the name; check the domain and the trademark.
2. Umesh sends the details in §1.
3. I make the domain one setting (§2B) and ship it on its own, with no visible change.
4. I change the visible name, logos, emails, invoices, WhatsApp templates and legal pages
   (§2A) and the docs (§2D), with the old domain still serving.
5. Umesh sets up §3: new domain, Cloudflare, Resend, mailboxes, OAuth and Meta, Razorpay.
6. Deploy serving both domains; switch the console settings to the new domain.
   **Emails (D-933), in this order:** (a) Resend shows the new domain verified;
   (b) set `notifications_from`, `sender_security`, `sender_billing`, `sender_alerts`,
   `sender_operator` and `notifications_reply_to` in the ops console to the addresses in
   `docs/EMAILS.md` §2; (c) change `brand.PRODUCT`, `brand.TAGLINE`, `brand.LOGO_URL`,
   `brand.LEGAL_ENTITY_NAME`/`REGISTERED_ADDRESS` (with `placeholders.ts`) and
   `console_links.DOMAIN`; (d) move each email onto `email_render.product_email` with the
   wording in `docs/EMAILS.md` §3 and add the sender display names; (e) send one of each
   purpose to a Gmail and an Outlook inbox and check From, Reply-To, logo and footer.
7. The internal names (§2C, `docs/rebrand/INFRA-DEPLOY-ENV.md` and
   `DATA-AND-INTEGRATIONS.md`) in one maintenance window, backups first.
8. Old domain redirects to the new one. Keep `calevate.tech` registered for at least 12 months
   (links, webhooks, OAuth registrations and anyone who saw the old name).
