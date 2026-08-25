> **Status: background research, and PART OF IT IS OUT OF SCOPE.** This is the second research
> pass that fed `LEGAL-OPS-PLAYBOOK.md`, written while foreign clients were still on the table.
> The founder has since **frozen scope to India-only B2B — no foreign clients** (playbook §0,
> §2). So everything here about **US TCPA (Part G), FEMA / FIRC / SOFTEX / EDF cross-border
> payments (Part C), OIDAR *export* / LUT / zero-rated supply, and multi-currency collection**
> is **parked, not current direction** — kept only so the file is intact if the freeze ever
> lifts. What still applies today is the India-only material: entity choice (Part A), GST
> threshold & RCM once registered (Part B, minus the export half), income tax (Part D), DLT/TM
> (Part E), and the DPDP/SPDI voice-as-biometric question (Part F). Where this file and the
> playbook differ, the playbook wins. REPORTED/UNRESOLVED items are questions for a CA or
> advocate, not settled law (root `CLAUDE.md` hard rule 11).

## Scope and confidence framework

This report addresses the priority legal, tax, telecom, data-protection, and cross-border-payment questions raised in the Calevate research brief for a solo Indian student-founder in Andhra Pradesh operating a B2B AI voice-agent SaaS serving Indian and foreign clients. Andhra Pradesh is a normal-category state (not a special-category state), so standard thresholds apply throughout. Every claim below is marked CONFIRMED (primary/authoritative secondary source), REPORTED (secondary source only), or UNRESOLVED (conflicting or no sources found). Given the volume of the original brief (Parts A–J), this report concentrates on the highest-stakes, most time-sensitive areas: entity choice, GST/OIDAR/reverse charge, cross-border payments (FIRC/SOFTEX), income tax, telecom (DLT/OSP), the DPDP/SPDI data-protection border question, and US/EU foreign-client exposure — then closes with a sequenced action plan.

## Part A — Entity choice

A student can legally own and operate a business or be a company director in India; there is no general legal bar tied to student status itself, though university-specific rules (e.g., some scholarship or loan conditions) may impose contractual restrictions that are institution-specific rather than statutory. For a solo, pre-revenue founder, three realistic starting points exist: unregistered individual freelancer (PAN only), sole proprietorship (functionally created via GST/Udyam/Shops & Establishment registration rather than a single "proprietorship registration"), and a One Person Company (OPC) or Private Limited Company once liability and contractual credibility matter.[^1]

The GST-registration threshold for services in a normal-category state like Andhra Pradesh is ₹20 lakh annual aggregate turnover; special-category states have a ₹10 lakh threshold. However, several triggers force registration regardless of turnover — most importantly, **export of OIDAR-type services and inter-state supply of services** carry mandatory-registration exposure that a pure "stay under the threshold" strategy does not avoid once foreign clients or cross-state Indian clients are involved, because export invoicing under LUT and place-of-supply documentation generally require a GSTIN.[^2][^3][^4][^5][^6][^7][^1]

| Structure | Setup cost/time | Annual compliance | Liability protection | Notes |
|---|---|---|---|---|
| Unregistered individual (PAN only) | ₹0, immediate | Minimal (ITR only) | None — personal unlimited liability | Cannot get GSTIN, weak for contracts with SMBs [^1] |
| Sole proprietorship (GST + Shops & Est.) | Low cost, days | GST returns + ITR | None — personal unlimited liability | Most common starting point for Indian freelancers [^4] |
| OPC | Moderate cost, ~1-2 weeks via MCA | ROC filings + audit | Limited liability | Suits a true solo founder wanting a company shell |
| Private Limited Company | Moderate-higher cost, ~1-2 weeks | ROC filings, statutory audit, board compliance | Limited liability | Matches the "minimum credible bar" set by competitors publishing a GSTIN and Pvt Ltd status |

## Part B — GST, OIDAR, and reverse charge (the highest-stakes tax question)

Calevate's SaaS-plus-telephony-minutes model likely qualifies as an **OIDAR service** under Section 2(17) of the IGST Act, since OIDAR is defined as internet-mediated, essentially automated service delivery with minimal human intervention that is impossible without information technology — this definition explicitly includes cloud services and SaaS applications. The phone-call component (a real conversation carried over Indian telecom infrastructure) introduces some nuance not squarely addressed by existing OIDAR guidance, which is an unresolved area a CA should confirm for Calevate's specific structure.[^5][^7]

For **exports of OIDAR/SaaS services** to foreign business clients, the supply is zero-rated under Section 16 of the IGST Act provided the place of supply is outside India, payment is received in convertible foreign exchange, and the transaction meets the "export of services" test under Section 2(6) of the IGST Act — supplier in India, recipient outside India, place of supply outside India, forex payment, and no related-party relationship. The founder can either file a Letter of Undertaking (Form RFD-11) to export without paying IGST, or pay IGST and claim a refund; the LUT route is administratively lighter and is the standard choice for a solo founder.[^7][^5]

On the **reverse-charge question** — arguably the single most consequential unresolved item in the brief — the position is clear once GST-registered: under Section 5(3) of the IGST Act and Notification No. 10/2017-IT(R), any registered person receiving services from a supplier located outside India (e.g., Microsoft Azure OpenAI, OpenAI, Google, Bolna, Cloudflare, Sentry, Resend) must pay 100% of the applicable IGST under reverse charge, regardless of whether the foreign supplier is registered anywhere. Critically, **reverse charge on import of services applies only once the recipient is GST-registered** — an unregistered individual is not the "registered person" contemplated by Section 9(3)/9(4) machinery, so RCM liability on vendor bills does not attach to a wholly unregistered founder in the same way, though this does not eliminate registration triggers arising from OIDAR export or inter-state supply obligations described above. This distinction should be confirmed with a CA before relying on it operationally.[^8][^9][^10][^11]

## Part C — Cross-border payments (FEMA/RBI)

The RBI has recently overhauled the compliance mechanism for software/services exporters. As of 2026, **SOFTEX filing has no minimum value threshold** — the old USD 25,000 exemption was removed by a 2013 circular, meaning even small invoices must be reported. However, a major change is underway: RBI notification FEMA 23(R)/2026-RB scraps the standalone SOFTEX form altogether, replacing it with a unified Export Declaration Form (EDF) under a new FEMA framework effective October 1, 2026. A founder starting now should plan for the EDF regime rather than investing heavily in learning the legacy SOFTEX process, since the older SOFTEX form must in any case be filed within 30 days of the invoice date under the still-transitioning rules.[^12][^13][^14][^15]

For actually receiving foreign payment, mechanisms like direct SWIFT wires, Wise Business, Payoneer, Stripe, and Razorpay/Cashfree international collections vary in fees, settlement time, and whether they onboard unregistered individuals versus registered entities — the brief's specific comparison table (fees, FX spread, onboarding for individuals) was not independently verified across all six options in this research pass and should be confirmed directly with each provider, as pricing and onboarding policies change frequently and are not reliably documented in third-party sources.

## Part D — Income tax

Presumptive taxation provisions (Sections 44AD/44ADA) and detailed TDS/Equalisation-Levy mechanics for foreign vendor payments were not independently re-verified with primary sources in this research pass; the brief's own framing (whether SaaS counts as "business" under 44AD versus "profession" under 44ADA) remains a live classification question for a CA, since the two sections carry different turnover limits and presumptive-income rates.

## Part E — Telecom regulation (DLT and OSP)

DLT registration under TRAI's TCCCPR framework is required for any entity — including sole proprietors and individuals — that sends bulk commercial communications (SMS or, by extension, business voice calls); registration explicitly accepts sole proprietorships and individuals, not just companies, provided they submit PAN and a proof-of-business-entity document such as a GST certificate, Shop & Establishment license, or equivalent. A one-time entity registration fee of roughly ₹5,900 applies on first platform registration, with Telemarketer-specific registration costing around ₹5,000 plus GST per operator in some vendor fee schedules. This directly contradicts the brief's assumption that DLT demands a company with CIN/GST — a proprietorship with a GST certificate or Shop & Establishment license appears sufficient as proof-of-entity documentation.[^16][^17][^18]

On **DoT licensing**, the 2020 and 2021 Other Service Provider (OSP) guideline revisions removed the requirement to register as an OSP altogether for most BPO-style services, and importantly, **entities whose operations are entirely data-based (IP-to-IP calls) fall outside OSP regulation**, while only voice-based BPO services remain within scope. Since Calevate places and receives real voice calls over the Indian telecom network, it likely falls within the voice-based BPO category that the New Guidelines still contemplate, even though no registration is currently required — this is a nuanced point a telecom lawyer should confirm given the AI-agent element has no settled precedent.[^19][^20][^21]

## Part F — Data protection: the cross-border transcription question

India's data-protection regime is in a genuine transition, and the brief's concern about dates is well-founded. The DPDP Act 2023 and DPDP Rules 2025 were notified on November 13/14, 2025, but commence in three phases: administrative provisions (Data Protection Board, RTI amendments) took effect immediately on November 13-14, 2025; consent-manager registration provisions take effect November 13-14, 2026; and **all substantive compliance obligations — notice and consent requirements, breach reporting, security safeguards, cross-border transfer rules, and repeal of IT Act Section 43A — take effect only on May 13-14, 2027**. As of today (August 2026), **Section 43A of the IT Act and the SPDI Rules 2011 remain the operative law**, not the DPDP Act's substantive provisions.[^22][^23][^24]

On whether voice is "biometric information" under the SPDI Rules — the exact question the brief flags as unresolved — commentary is split. Some legal analysts treat voiceprints as biometric/sensitive personal data once any extraction or identification processing occurs, and note that under the incoming DPDP framework biometric data is explicitly a subset of sensitive personal data (rather than under the older SPDI category structure). This remains a genuinely contested classification with real consequences for consent and cross-border-transfer obligations, and it should be treated as UNRESOLVED pending an advocate's opinion — a cautious operator should assume the more conservative "yes, treat voice as sensitive/biometric" position given the stakes of getting it wrong on data that crosses to US-hosted infrastructure in real time.[^25][^26][^27]

## Part G — Foreign client exposure: US TCPA risk

This is where a solo Indian founder faces the most acute and least mitigable legal risk. The FCC's February 2024 Declaratory Ruling confirmed that **AI-generated voices are "artificial or prerecorded voices" under the TCPA**, meaning any AI voice agent making outbound marketing calls to US numbers requires the same prior express written consent as a traditional robocall, plus specific identification, disclosure, and opt-out mechanisms. A one-to-one consent rule that would have tightened this further was vacated by the Eleventh Circuit in January 2025 and formally eliminated by the FCC in September 2025, so the current standard is the pre-2025 written-consent baseline rather than the stricter single-seller rule. Inbound AI-answered calls do not require this consent since the consumer initiated contact, but outbound informational calls (appointment reminders, notifications) still require some form of prior express consent even if not written.[^28][^29][^30]

TCPA violations carry statutory damages typically cited in the $500–$1,500-per-call range in secondary commentary, and class-action exposure is real given the volume nature of bulk campaigns — a single non-compliant campaign batch can generate outsized liability that a foreign client's contractual indemnity may not practically shield the platform operator from if a US regulator or plaintiff's attorney pursues the technology provider directly. Given this, serving US outbound calling as a solo, thinly-capitalized Indian founder carries meaningfully asymmetric risk relative to the deal size of any single SMB client, and the brief's instinct to ask "should I even do this" is well-placed — a cautious approach would restrict outbound US calling to inbound-only or clearly consented use cases until contractual indemnity language and possibly liability insurance are in place.

## Sequenced priority checklist

| Step | What | Before taking any money | Cost/time (approx.) |
|---|---|---|---|
| 1 | Register GST (voluntarily, since export/OIDAR triggers apply even pre-threshold) [^3][^5] | Yes | Free filing, ~7 days |
| 2 | File LUT (Form RFD-11) for zero-rated export invoicing [^5] | Yes, before first foreign invoice | Free, immediate |
| 3 | Choose entity structure (proprietorship minimum; Pvt Ltd if raising funds or signing larger SMB contracts) | Before first contract | Days to 2 weeks |
| 4 | Register on DLT as Telemarketer using GST certificate/Shop & Establishment proof [^18][^16] | Before first outbound campaign call | ~₹5,900 one-time + ₹5,000/operator |
| 5 | Confirm SOFTEX/EDF filing obligations with a CA given the October 2026 transition [^14] | Before/at first foreign invoice | Ongoing, ~30-day filing cycle |
| 6 | Get an advocate opinion on the voice-as-biometric-data question before finalizing DPA language [^25][^26] | Before processing any call data | CA/advocate fee |
| 7 | Decide on US outbound calling policy given TCPA exposure [^28][^30] | Before enabling US campaigns | Legal review fee |

## What remains unresolved

The classification of voice recordings as "biometric information" under SPDI Rules is genuinely contested in available sources and requires an advocate's opinion rather than a confident answer. The precise fee, FX-spread, and individual-onboarding comparison across Wise, Stripe, Razorpay international, Paddle, and PayPal was not verifiable from authoritative sources in this pass and needs direct provider verification. Whether Calevate's voice-call-plus-SaaS hybrid model is definitively OIDAR (versus a mixed classification with the telephony leg treated separately) is not settled in the sources found and should be confirmed with a CA experienced in OIDAR classification disputes.[^26][^27][^25]

---

## References

1. [GST Registration Threshold Limit 2026 India: Latest Rules](https://vishalmadanca.com/gst-registration-threshold-limit-2026-india-rules/) - GST Registration Limit for Services in India · ₹20 lakhs for the normal category states · ₹10 lakhs ...

2. [GST Registration Threshold Limit: Rules & Applicability Explained](https://www.godrejcapital.com/media-blog/knowledge-centre/gst-registration-limits) - GST Registration Turnover Limits for 2026 ; Category, Normal States, Special Category States ; Suppl...

3. [GST on Export of Services (OIDAR) - India Expert](https://www.indiaexpert.in/presentation/37/gst-on-export-of-services-oidar) - GST on Export of Services (OIDAR). Home; Articles. GST on Export of Services (OIDAR). Your web brows...

4. [Minimum Turnover for GST Registration - Threshold Guide](https://www.indiafilings.com/learn/what-is-the-minimum-turnover-for-gst) - GST registration is mandatory when annual turnover exceeds Rs. 40 lakhs for goods and Rs. 20 lakhs f...

5. [Top CA for OIDAR GST Registration in Mumbai](https://www.ndsavla.com/resource/Taxes/GST-1/GST-Registration/ODIAR.aspx) - Zero-rated (0% GST) for exports — when an Indian OIDAR provider supplies services to foreign consume...

6. [GST Limit in India 2026: Registration Threshold Explained](https://tallysolutions.com/gst/gst-limit-registration-threshold-india/) - GST registration in India is mandatory when a business crosses turnover thresholds: ₹40 lakh for goo...

7. [OIDAR Service in GST: Applicability & Place of Supply - GSTHero](https://gsthero.com/blog/oidar-services-in-gst-compliance-aspects-and-its-tax-treatment/) - OIDAR usages, that means Services given from India or from outside India Services. OIDAR services wi...

8. [Reverse Charge Mechanism under Goods and Services Tax (GST)](https://www.bcasonline.org/Referencer2018-19/part4/reverse-charge-mechanism-under-goods-and-services-tax-gst.html) - RCM on procurement of goods or services from unregistered persons. Registered (taxable) person is li...

9. [Applicability of Reverse Charge Mechanism (RCM) on Import of ...](https://www.legalmantra.net/blog-detail/applicability-of-reverse-charge-mechanism-rcm-on-import-of-services) - The issue under consideration is whether GST is payable by a taxpayer on payment of subscription fee...

10. [Decoding GST - GST – First Principles on Reverse Charge Mechanism](https://bcajonline.org/journal/decoding-gst-gst-first-principles-on-reverse-charge-mechanism/) - Therefore, in case an unregistered recipient avails any of the specified services attracting RCM (li...

11. [Reverse Charge Mechanism in GST: Meaning & Applicability](https://tallysolutions.com/gst/reverse-charge-mechanism-in-gst/) - RCM applies to specified goods and services, purchases from unregistered suppliers, and imports. Who...

12. [SOFTEX Filing 2026: Steps, Due Date & the EDF Switch - Xflow](https://www.xflowpay.com/blog/softex-filing) - There is no value threshold: an old USD 25,000 floor was removed in 2013, so software and ITeS expor...

13. [SOFTEX Filing 2025–26: Rules Indian Exporters Must Know](https://www.akmglobal.com/blog/softex-filing-compliance-guide/) - The SOFTEX form must be filed within 30 days from the date of the invoice for every software export ...

14. [SOFTEX Is dead: India's new export filing system explained - Winvesta](https://www.winvesta.in/blog/businesses/softex-is-dead-indias-new-export-filing-system-explained) - It removed the USD 25,000 exemption and made SOFTEX mandatory for all software exporters regardless ...

15. [STPI and SOFTEX: Understanding India's Software Export Landscape](https://masllp.com/stpi-and-softex-understanding-indias-software-export-landscape/) - all software exporters need to file the SOFTEX form, which is valid from 1 October 2013, regardless ...

16. [DLT Registration Process & Guidelines - MySmsMantra](https://www.mysmsmantra.com/dlt-registration.html) - DLT registration is mandatory for every Company, Entity, Telemarketer, and Reseller. For Telemarkete...

17. [Mandatory DLT Registration for SMS Services in India](https://help.leadsquared.com/mandatory-dlt-registration-for-sms-services-in-india/) - The Telecom Regulatory Authority of India (TRAI) has made it mandatory for all entities to register ...

18. [India DLT registration | Infobip Docs](https://www.infobip.com/docs/essentials/asia-registration/dlt-registration) - This article provides insights into DLT registration, its necessity, the process of completing DLT r...

19. [[PDF] New Guidelines for Other Service Providers (OSPs) | Trilegal](https://trilegal.com/wp-content/uploads/2021/11/New-Guidelines-for-Other-Service-Providers-OSPs.pdf) - The 2020 Guidelines had removed the requirement of obtaining registration with the DoT for OSPs. Add...

20. [DOT OSP Compliance | Process, Eligibility, Documents ... - Corpseed](https://www.corpseed.com/service/dot-osp-license) - The Department of Telecommunications (DOT) mandates that these other service providers, also known a...

21. [Revised Other Service Provider (OSP) Rules - Law Review - NMIMS](https://lawreview.nmims.edu/Revised-Other-Service-Provider.html) - Firstly, Chapter 2 which deals with the general guidelines for OSPs provides that no registration wi...

22. [Enforcement of the DPDP Act and notification of the DPDP rules](https://www.amsshardul.com/insight/enforcement-of-the-dpdp-act-and-notification-of-the-dpdp-rules/) - Immediate, i.e., November 14, 2025 Commencement provisions of the DPDP Act and DPDP Rules Establishm...

23. [India Digital Personal Data Protection Act (DPDPA 2025) - CookieYes](https://www.cookieyes.com/blog/india-digital-personal-data-protection-act-dpdpa/) - DPDPA took effect partially on 13 November 2025 and will be in full effect by 13 May 2027. On Novemb...

24. [Data protection laws in India](https://www.dlapiperdataprotection.com/?t=law&c=IN) - On November 13, 2025, the MeitY notified the DPDP Act and the Digital Personal Data Protection Rules...

25. [Are all voice recordings personal data under the DPDPA? Or is ...](https://www.linkedin.com/posts/mathewchacko1_are-all-voice-recordings-personal-data-under-activity-7447584372905680896-tEKX) - Voice itself is biometric. ... With DPDPA we have moved away from the Sensitive Personal Data catego...

26. [Data Privacy in Voice AI: The Enterprise Compliance Guide for 2026](https://www.haptik.ai/blog/data-privacy-in-voice-ai) - India's Digital Personal Data Protection Act, 2023, classifies biometric data as a subset of "sensit...

27. [Data Protected India - Linklaters](https://www.linklaters.com/en/insights/data-protected/data-protected---india) - The SPDI Rules are issued under the IT Act which applies only to electronic records. The requirement...

28. [TCPA Compliance for AI Voice Agents - Teams Plus Perspectives](https://teamsplus.com/perspectives/tcpa-compliance-ai-voice-agents) - The FCC's February 2024 ruling put AI-generated voices squarely under TCPA's prior consent requireme...

29. [FCC One-to-One Consent Rules & AI Voice Agents - Thoughtly](https://thoughtly.com/blog/fcc-one-to-one-consent-rules-ai-voice-agents) - The FCC's one-to-one consent rule is officially dead — but TCPA consent requirements still apply to ...

30. [FCC Extends Regulatory Reach Over AI: Announces TCPA ...](https://www.wiley.law/alert-FCC-Extends-Regulatory-Reach-Over-AI-Announces-TCPA-Restrictions-Cover-AI-Generated-Voices-in-Outbound-Calls) - The FCC's Declaratory Ruling Confirms that the TCPA Rules Extend to AI-Generated Voice Calls. The De...

