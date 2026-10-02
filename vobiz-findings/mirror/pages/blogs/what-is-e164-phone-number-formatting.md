> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is E.164 Phone Number Formatting? The Complete Guide (2026)

> E.164 is the global standard for phone numbers: +country code, up to 15 digits, no leading zeros. How it works, examples by country, and how to validate it.

*June 22, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

E.164 is the international standard that defines how a telephone number is written so it can be routed anywhere on the global phone network. An **E.164 phone number** is a single, globally unique string: a leading `+`, a country calling code, and the rest of the national number, with a hard ceiling of 15 digits and no leading zeros. If you have ever passed a phone number into a voice or SMS API and been rejected with an "invalid number format" error, E.164 is almost always what the API expected.

This guide goes well past the one-line definition: the exact anatomy of an E.164 number, worked examples across the US, India, the UK and more, why every serious telephony API insists on it, how it compares to national and international and `tel:` URI formats, the mistakes that break real integrations, and how to format and validate numbers with `libphonenumber`, with a specific lens on what E.164 means when the call is carrying a voice AI agent.

<Note>
  **Key takeaways**

  * **E.164** is the ITU-T standard for international phone numbers: `+` followed by a **country code**, **national destination code**, and **subscriber number**, **maximum 15 digits**, no spaces, no leading zero.
  * It exists so that one canonical string routes a call or message to exactly one device anywhere in the world, no ambiguity between countries.
  * Almost every [Voice API](/docs/blogs/what-is-a-voice-api) and SMS API requires E.164 because it removes formatting guesswork from routing, deduplication, and deliverability.
  * The common breakages: keeping a national leading `0`, using `00` instead of `+`, leaving spaces/dashes in, or storing the number as a non-canonical national format.
  * Use Google's [`libphonenumber`](https://github.com/google/libphonenumber) (or a provider lookup) to parse, validate, and normalize to E.164 before you store or dial.
</Note>

## What is E.164?

[E.164 is the ITU-T recommendation that defines the international public telecommunication numbering plan](https://www.itu.int/rec/T-REC-E.164/en), the rulebook that prescribes how telephone numbers are structured so calls and messages route correctly across the Public Switched Telephone Network (PSTN) and the networks layered on top of it. The standard is maintained by the **Telecommunication Standardization Sector (ITU-T)** of the International Telecommunication Union, the United Nations agency for telecommunications.

The one distinction that matters: E.164 is a **canonical, globally unambiguous** representation. The same physical phone can be written dozens of human-friendly ways, `(415) 555-2671`, `0415 555 2671`, `+1 415-555-2671`, but it has exactly **one** E.164 form. That canonical form is what lets a system in Bengaluru route a call to a handset in San Francisco without having to know the local dialing conventions of either place.

E.164 is the successor to the older E.163 recommendation; the two were merged in the late 1990s when the standard was retitled for the ISDN era, and E.164 has been the basis of global numbering ever since.

## The anatomy of an E.164 number

Every E.164 number is built from the same three parts, written with no separators, after a single leading `+`:

```
+    1        415          5552671
│    │        │            │
│    │        │            └── Subscriber Number (SN)
│    │        └─────────────── National Destination Code (NDC) / area code
│    └──────────────────────── Country Code (CC)
└───────────────────────────── the leading "+"
```

**The leading `+`.** Not a digit, but a marker. It tells any system, and any human, "what follows is an international number, interpret the next digits as a country code." The `+` is a placeholder for whatever international call prefix the originating network actually uses (`00` in much of Europe and India, `011` in North America). Storing the `+` instead of a hardcoded `00`/`011` is what keeps a number portable between countries.

**The country code (CC).** One to three digits, assigned by the ITU. `1` covers the US, Canada and the North American Numbering Plan; `44` is the United Kingdom; `91` is India; `81` is Japan. No country code begins with `0`, which is exactly why a valid E.164 number can never start with `+0`. The full list is published by the ITU and mirrored on [Wikipedia's list of country calling codes](https://en.wikipedia.org/wiki/List_of_country_calling_codes).

**The national destination code (NDC).** Often called the area code or, for mobiles, the operator/prefix code. It identifies a region or a carrier within the country. Its length varies by country, three digits in the US (`415`), two in London (`20`), and in some plans it is folded into the subscriber number entirely.

**The subscriber number (SN).** The digits that identify the specific line within that NDC.

**The 15-digit maximum.** This is the rule people miss most. [The total length of an E.164 number, excluding the `+`, must not exceed 15 digits](https://en.wikipedia.org/wiki/E.164). The country code consumes the first one to three of those, so the combined NDC plus subscriber number can be at most `15 minus the country-code length` digits. There is no fixed minimum across all countries, but real numbers are typically eight to fifteen digits long.

So a fully valid E.164 number is: `+` then 1–3 country-code digits then the national number, decimal digits only, no spaces, no parentheses, no dashes, total digits ≤ 15.

## E.164 examples by country

The fastest way to internalize E.164 is to see the same kind of number, as a person would write it locally, transformed into its canonical form. Note how the **national leading `0`** disappears and the country code replaces it.

| Country | Country code | How it's written locally | E.164 format |
| - | - | - | - |
| United States | 1 | (415) 555-2671 | `+14155552671` |
| Canada | 1 | (604) 555-0188 | `+16045550188` |
| India (mobile) | 91 | 098765 43210 | `+919876543210` |
| United Kingdom | 44 | 020 7183 8750 | `+442071838750` |
| Germany | 49 | 030 901820 | `+4930901820` |
| France | 33 | 06 12 34 56 78 | `+33612345678` |
| Brazil | 55 | (11) 95525-6325 | `+5511955256325` |
| Australia | 61 | 0412 345 678 | `+61412345678` |
| Japan | 81 | 090-1234-5678 | `+819012345678` |
| Singapore | 65 | 8123 4567 | `+6581234567` |
| South Africa | 27 | 082 123 4567 | `+27821234567` |
| UAE | 971 | 050 123 4567 | `+971501234567` |

Two patterns to take away. First, the local **trunk prefix `0`** (the `0` you dial before a domestic number in the UK, India, Germany, Australia, South Africa and many others) is **never** part of the E.164 number, you drop it and prepend the country code. Second, the digits are run together; the spaces and brackets above are only for human readability and must be stripped before the string is valid E.164.

## Why APIs require E.164

If you have integrated a [Voice API](/docs/blogs/what-is-a-voice-api), an SMS API, or a [number-lookup](/docs/account-phone-number) endpoint, you have met the "must be E.164" rule. There are three concrete engineering reasons providers enforce it.

**Unambiguous routing.** A telephony platform has to decide which carrier and which country a call belongs to before it can place it. A bare `5552671` could be a thousand different lines in a hundred different countries. `+14155552671` resolves to exactly one. E.164 removes the guesswork from [SIP trunking](/docs/concepts/sip-trunking) and call routing, the country code drives carrier selection, and the rest drives the final leg. When you set a destination on a [`<Dial>`](/docs/xml/dial) or place an [outbound call](/docs/solutions/automated-outbound-calling), E.164 is what the platform expects.

**Deduplication and identity.** Because E.164 is canonical, it is a reliable database key. Store `+919876543210` and you can match a returning user, dedupe a contact list, and join records across SMS, voice and WhatsApp without worrying that one row says `09876543210` and another says `91 98765 43210`. Inconsistent formats are a leading cause of duplicate customer records and failed lookups.

**Deliverability and compliance.** Carriers, spam-analytics firms and regulators reason about numbers in canonical form. Sending a campaign with malformed numbers wastes spend on undeliverable attempts and can hurt your [number reputation](/docs/blogs/what-is-number-masking). In regulated markets like India, consent and registration frameworks such as [DLT](/docs/best-practices/dlt-registration) and the [TRAI calling rules](/docs/compliance/india/calling-regulations) are keyed to properly identified numbers, so normalization is a prerequisite, not a nicety.

In short: E.164 is the contract that lets your application and the telephony network agree on *which* phone you mean.

## E.164 vs national, international, and RFC 3966 `tel:` formats

E.164 is not the only way to write a number, it is the canonical machine form. Here is how it relates to the formats you'll see in the wild.

| Format | Example (same UK number) | Where it's used |
| - | - | - |
| **E.164** | `+442071838750` | APIs, databases, routing, the canonical store form |
| **National** | `020 7183 8750` | How a local person dials and reads it; includes the trunk `0` |
| **International (display)** | `+44 20 7183 8750` | Human-readable international; E.164 with spacing added |
| **RFC 3966 `tel:` URI** | `tel:+44-20-7183-8750` | Clickable links and SIP; the IETF URI scheme for telephone numbers |

The relationships are simple. **National format** is for humans inside one country and carries the trunk prefix. **International display format** is E.164 with cosmetic spaces, strip the spaces and you have E.164. The [`tel:` URI defined in RFC 3966](https://datatracker.ietf.org/doc/html/rfc3966) wraps a *global* (E.164-style) number in a URI scheme so it can appear in HTML links and SIP signaling; its global-number form is E.164 with optional visual separators. The practical rule: **display** numbers in national or pretty-international format, but **store and transmit** them in raw E.164.

## Common E.164 mistakes and errors

Most "invalid phone number" failures come from a small set of formatting bugs. These are the ones that cause real API rejections.

**Keeping the national leading `0`.** The single most common mistake. A UK number is `+44 20 ...`, not `+44 020 ...`; an Indian number is `+91 98765 43210`, not `+91 098765 43210`. The trunk `0` is a domestic dialing instruction, not part of the number, prepending the country code replaces it.

**Using `00` (or `011`) instead of `+`.** Writing `0044207...` or `01144207...` embeds a *region-specific* international prefix into the stored number. E.164 uses the `+` marker precisely so the number is independent of where the call originates. Replace the leading `00`/`011` with `+`.

**Leaving spaces, dashes, dots, or brackets in.** `+1 (415) 555-2671` is fine for a person but invalid as a stored E.164 string. Strip everything that isn't a digit (after preserving the leading `+`). E.164 is digits only.

**Omitting the country code.** A national number with no country code (`4155552671`) is ambiguous and will be rejected by international routing, or worse, silently misrouted if a default country is assumed wrong.

**Exceeding 15 digits.** Concatenating an extension, an extra prefix, or a doubled country code (`+9191...`) can push past the 15-digit ceiling and fail validation outright.

**Storing display format in the database.** Even if a number passes once, mixing national and E.164 forms in storage breaks deduplication and joins later. Normalize *on input*, store one canonical E.164 string.

On Vobiz, malformed destinations surface as a validation error in the API response, see the [error handling reference](/docs/errors) for the standard payload, so it pays to normalize before you ever hit the wire.

## How to format and validate E.164 (libphonenumber)

You should not roll your own E.164 parser, the country-by-country rules (variable NDC lengths, trunk prefixes, mobile vs fixed ranges) are too intricate. The de facto tool is Google's [`libphonenumber`](https://github.com/google/libphonenumber), the same library behind Android's dialer, with ports for Java, JavaScript, Python, Go, C++ and more.

The workflow is always the same: **parse** the raw input (with a default region for numbers that lack a `+`), **check validity**, then **format to E.164** for storage.

Here is the pattern in Python using the `phonenumbers` port:

```python theme={null}
import phonenumbers

raw = "(415) 555-2671"            # messy user input
# Parse with a default region so national-format input can be understood
num = phonenumbers.parse(raw, "US")

# Is it a plausible, valid number for its region?
if phonenumbers.is_valid_number(num):
    e164 = phonenumbers.format_number(
        num, phonenumbers.PhoneNumberFormat.E164
    )
    print(e164)               # -> +14155552671
else:
    print("Invalid number")
```

And in JavaScript with `libphonenumber-js`:

```javascript theme={null}
import { parsePhoneNumberFromString } from "libphonenumber-js";

const num = parsePhoneNumberFromString("020 7183 8750", "GB");

if (num && num.isValid()) {
  console.log(num.format("E.164"));   // -> +442071838750
}
```

A few practical rules when validating:

* **Always pass a default region** for input that might be in national format; without it, a number lacking `+` can't be interpreted.
* **Prefer `isValidNumber` over `isPossibleNumber`** when you can, the former checks the number against the country's actual numbering plan, not just length.
* **Validate at the edge**, normalize on form submit and store only the E.164 string, so everything downstream is already canonical.
* **For high-stakes flows** (fraud, deliverability), pair format validation with a live number-lookup that confirms the line type and carrier.

Once you have a clean E.164 string, you can safely store it, dedupe on it, and hand it to your telephony provider.

## How Vobiz handles E.164

[Vobiz](/docs/introduction) is the telephony **infrastructure** layer, the rails that carry calls for voice-AI builders, so consistent number handling sits at the core of the platform rather than being an afterthought.

* **E.164 end to end.** Numbers you [provision from inventory](/docs/account-phone-number/purchase-from-inventory) or [list](/docs/account-phone-number/list-inventory-numbers) are represented in canonical E.164, and the [Voice API](/docs/blogs/what-is-a-voice-api) expects E.164 destinations on [`<Dial>`](/docs/xml/dial) and [outbound calls](/docs/solutions/automated-outbound-calling), so the same string works for routing, [call logs](/docs/platform/voice/call-logs), and dedup.
* **Global reach, one format.** DID provisioning in **130+ countries** and outbound connectivity to **190+ countries**, all addressed with the same E.164 scheme over [SIP trunking](/docs/platform/sip/overview) or WebSockets, no per-country dialing quirks to encode in your app.
* **Validation that fails fast.** Malformed destinations return a structured error (see the [error reference](/docs/errors)) instead of silently misrouting, so you catch a missing country code or stray leading `0` in development, not in production.
* **Built for voice AI.** Because Vobiz powers agents on Vapi, Retell, ElevenLabs, Pipecat, and LiveKit, clean E.164 handling pairs with **sub-80 ms** single-hop latency and bidirectional audio streaming, so the latency budget goes to the conversation instead of number routing.
* **India-first compliance.** E.164 normalization dovetails with [TRAI calling rules](/docs/compliance/india/calling-regulations) and [DLT registration](/docs/best-practices/dlt-registration), and flat ₹0.65/min pricing for both inbound and outbound.

Vobiz doesn't build the agent, it gives the agent a correctly-formatted, instantly-routable line. Builders like **Bolna**, fintechs like **Razorpay** and **Acko**, and enterprises like **KPMG** run their voice traffic on these rails.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What does E.164 stand for?">
    E.164 isn't an acronym, it's the number of the ITU-T recommendation that defines the international public telecommunication numbering plan. The standard specifies how phone numbers are structured for global routing: a leading `+`, a country code, and the national number, up to 15 digits total.
  </Accordion>

  <Accordion title="What is the maximum length of an E.164 number?">
    Fifteen digits, not counting the leading `+`. The country code uses the first one to three of those digits, so the national destination code plus subscriber number can be at most 15 minus the country-code length.
  </Accordion>

  <Accordion title="Does an E.164 number include a leading zero?">
    No. The national trunk prefix `0` that you dial inside many countries is dropped in E.164. For example, UK `020 7183 8750` becomes `+442071838750`, the `0` is removed and the `44` country code is added.
  </Accordion>

  <Accordion title="What is the difference between E.164 and a national phone number format?">
    A national format is how a person dials and reads a number inside one country (often with a trunk `0` and spaces). E.164 is the canonical international form: `+`, country code, no trunk `0`, digits only. National format is for display; E.164 is for storage, routing, and APIs.
  </Accordion>

  <Accordion title="How do I convert a phone number to E.164 format?">
    Strip spaces, dashes and brackets, remove any national trunk `0`, and prepend `+` and the country code. In practice, use a library like Google's `libphonenumber`: parse the raw input with a default region, confirm it's valid, then format it to E.164.
  </Accordion>

  <Accordion title="Why does my voice or SMS API reject my phone number?">
    Almost always a formatting issue: a missing country code, a leftover leading `0`, spaces or dashes in the string, `00` used instead of `+`, or a number exceeding 15 digits. Normalize the number to canonical E.164 before sending it to the API.
  </Accordion>
</AccordionGroup>

## Further reading on Vobiz

* [What is a Voice API?](/docs/blogs/what-is-a-voice-api) · [What is SIP trunking?](/docs/blogs/what-is-sip-trunking) · [What is VoIP?](/docs/blogs/what-is-voip) · [What is number masking?](/docs/blogs/what-is-number-masking)
* [Phone numbers & DIDs](/docs/account-phone-number) · [Purchase a number](/docs/account-phone-number/purchase-from-inventory) · [SIP trunking overview](/docs/platform/sip/overview)
* [VobizXML: how it works](/docs/xml/overview/how-it-works) · [Dial](/docs/xml/dial) · [Error handling reference](/docs/errors)

## Sources

* ITU-T, ["E.164: The international public telecommunication numbering plan"](https://www.itu.int/rec/T-REC-E.164/en).
* Wikipedia, ["E.164"](https://en.wikipedia.org/wiki/E.164).
* Wikipedia, ["List of country calling codes"](https://en.wikipedia.org/wiki/List_of_country_calling_codes).
* Google, ["libphonenumber" (GitHub repository)](https://github.com/google/libphonenumber).
* IETF, ["The tel URI for Telephone Numbers" (RFC 3966)](https://datatracker.ietf.org/doc/html/rfc3966), December 2004.

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number in E.164 format and place your first programmable call in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.