# Rename map: Calevate → new name, and the new Udyam registration

Prepared 29 Oct 2026 at commit `1746978e` (tag `checkpoint-pre-rename-2026-10-29`). Counts are
`git grep -i calevate` over the tracked tree on that commit. Nothing here has been changed
yet; this is the map to work from once the name and the registration details are known.

**The size of it:** 7,253 mentions in 1,631 files. Most are internal names nobody outside
sees. The work splits into four kinds, each changed differently (§2).

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
| Emails: invitations, password reset, admin sign-in code, alerts, receipts | `apps/api/core/email_layout.py`, `alert_email.py`, `apps/workers/email_render.py` | sender is `notifications_from` (`config.py:1335`, today `support@calevate.tech`) |
| Invoices | `apps/api/billing/gst.py`, `invoice.py` | supplier name, registration, the "sole proprietorship below the threshold" sentence (`gst.py:85`) |
| Legal pages: Terms, Privacy, DPA, Acceptable use, Sub-processors, Refunds, Grievance, Cookies | `apps/web/src/lib/legal/*.ts` + `placeholders.ts` values | a **material** revision of every blocking document (§4) |
| WhatsApp templates submitted into each client's own WhatsApp account | `apps/api/whatsapp/templates.py`: names `calevate_booking_confirmed`, `calevate_details_you_asked_for`, `calevate_payment_link`, `calevate_call_back_time` | new names mean Meta re-approves them in every connected account; the old ones keep working meanwhile |
| Text we send to the voice platform that a person may read | `apps/api/engine/thinnest_customer_data.py:54` do-not-call reason "Calevate do-not-call list" | |
| What agents SAY on calls | **nothing** | checked: no "Calevate" in the prompt layers, notices, spoken style or call script. Callers hear the client's business name only (D-679) |

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
| Keys we put on every call at the voice platform: `calevate_call_id`, `calevate_lead_id`, `calevate_forwarding_leg`, idempotency prefixes `calevate-call-`, `calevate-customer-`, `calevate-fwd-` (`engine/thinnest.py:2761,2771,3395,3405`, `thinnest_customers.py:203`) | — | **calls in flight are matched by these; renaming needs a period where both are read** |
| R2 bucket names `calevate-call-recordings`, `calevate-db-backups` | settings + docs | a bucket cannot be renamed; it means a new bucket and copying every recording |
| GitHub repository name | — | GitHub redirects the old URL; update the VPS `git remote` |

None of these is visible to a client or a caller. Renaming them buys nothing a customer can
notice and carries the production risks in the right-hand column, so my recommendation is to
leave them and rename only §2A, §2B and the docs. If you still want "literally everywhere",
it is a separate, planned change after the visible switch, with its own maintenance window.

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

- **Every client's contract names the supplier.** Terms, DPA and Privacy are blocking
  documents, so a new legal entity there is a material revision: every client accepts again.
  Live agents keep taking calls meanwhile (D-926); going live, test copies and outbound wait
  for the acceptance.
- **Existing clients contracted with, and prepaid credit to, the old Udyam enterprise.** Moving
  them to the new one is a transfer of contracts (and of any unused credit). Ask the lawyer
  how to do it for a sole proprietorship moving to the new enterprise: a notice and fresh
  acceptance may be enough, or it may need an assignment clause.
- **Invoices** start a new number series under the new entity; past invoices stay as issued.
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
7. Old domain redirects to the new one; clients get an email; the new legal versions ask
   every client to accept.
8. After 12 months, and only then, consider letting `calevate.tech` lapse.
