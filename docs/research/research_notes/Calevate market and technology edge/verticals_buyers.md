# Indian SMB verticals and buyers for AI voice agents (as of Oct 2026)

All sources read 30 Oct 2026. Evidence class is on each line: VENDOR-CLAIM (self-published by a voice-AI or adjacent seller, no audit), PRESS (journalism quoting companies), SURVEY (third-party survey), JOB-SITE (salary aggregator). No independent, audited Indian study of voice-agent outcomes was found for any vertical: treat every outcome number below as a vendor claim unless it says otherwise.

## Which verticals and use cases get the most value, and what they need (per vertical)

### Takeaway
The best-evidenced verticals in India are BFSI (lending acquisition, collections, insurance renewals), e-commerce/D2C (COD confirmation and RTO), real estate (lead warm-up and site visits) and education (admissions). Named Indian deployments with numbers exist in each, but all figures are vendor-published. Clinics, auto-dealer service, hospitality and local services have only generic vendor marketing and no Indian outcome data found.

### Cited Findings

**Cross-vertical adoption order**
- Earliest adopters of voice AI in India are banking, financial services, e-commerce, retail and collections. Acquisition, cross-sell and collections get budget faster than support because their impact is easier to measure (PRESS, Inc42, 15 Jul 2026) — [Inc42](https://inc42.com/features/the-unit-economics-of-indias-voice-ai-boom/)

**Real estate**
- Anarock (a large Indian broker) built "Genie" voice agents on ElevenLabs. Claimed results: ₹2,000 crore of sales attributed to agent-assisted conversations; 8.5 million successful interactions in the last financial year, against 1.7 million by the human sales team; calling capacity up 5x without a matching rise in headcount; agent-assisted bookings doubled Jan–May 2026 (about 1,400 bookings); about 30% of conversations happen outside business hours. Use cases: lead warm-up, re-engaging cold leads, inbound overflow, channel-partner (broker) qualification with live transfer to a human. It has a separate southern-market voice for the Bengaluru area. VENDOR-CLAIM (ElevenLabs blog, 22 Jun 2026) — [ElevenLabs/Anarock](https://elevenlabs.io/blog/anarock)
- An unnamed Bangalore developer is claimed to have reached a 2-minute response time, 3x site visits, a 25% lead-to-visit rate and ₹1.2 Cr of pipeline. VENDOR-CLAIM, unnamed client — [Edesy](https://edesy.in/ai-voice-assistant/case-studies/real-estate)
- SquadStack's real-estate page claims 90% connectivity, 40% more conversions and 3x lower CAC than human agents. VENDOR-CLAIM — [SquadStack](https://www.squadstack.ai/real-estate)
- Haptik describes a "leading developer" that turned its inbound telephony into a site-visit booking channel. It gives no metrics. VENDOR-CLAIM — [Haptik](https://www.haptik.ai/blog/ai-voice-agent-use-cases-real-estate)
- Integration: LeadSquared is described as the dominant CRM for Indian real estate, edtech and financial services. VENDOR-CLAIM (third-party integration vendor) — [Caller.digital](https://caller.digital/blog/voice-ai-salesforce-hubspot-leadsquared-integration-india-2026)

**D2C / e-commerce (COD confirmation, NDR, RTO)**
- GoKwik network data for FY2022-23: 75% of orders were COD. It reports RTO held at 25% in one pre-festive period, and COD RTO cut by up to 18% for about 40% of its brands (by 30% for fashion and 38% for health and wellness). PRESS quoting the company — [Outlook Startup](https://startup.outlookindia.com/sector/e-commerce/ecommerce-brands-save-over-rs-130-cr-worth-of-rto-losses-in-2023-gokwik-news-9409); [CXOToday](https://cxotoday.com/media-coverage/1000-d2c-brands-kick-off-festive-season-with-20-rise-in-order-volume-gokwik/)
- Shiprocket says COD (non-prepaid) orders have an RTO rate of about 26%, against about 2% for prepaid. VENDOR-CLAIM (blog) — [Shiprocket](https://www.shiprocket.in/blog/order-value-recovery/amp)
- Estimates of COD's share of orders conflict: Shiprocket's blog says about 25–30% of transactions, ShipPrime says 50–70% of D2C GMV, and GoKwik says 75% of its network's orders. Scopes differ (all e-commerce vs D2C vs one checkout network). — [Shiprocket](https://www.shiprocket.in/blog/order-value-recovery/amp); [ShipPrime](https://shipprime.live/resources/blogs/cod-vs-prepaid-rto-profitability)
- "UrbanKart" COD confirmation calls are claimed to have cut RTO from 22% to 14% and converted 18% of COD orders to prepaid. The claimed ₹1.25 Cr annual benefit does not reconcile with its own table. VENDOR-CLAIM — [Edesy](https://edesy.in/ai-voice-assistant/blog/ai-voice-agent-case-study-ecommerce)
- Caller.digital claims an average 40% RTO reduction after 60 days, typically from a 28–35% baseline to 18–22%. It is Shopify/WooCommerce native. VENDOR-CLAIM — [Caller.digital](https://caller.digital/ai-voice-bot-for-cod-verification)
- Workflow needed: an order webhook from Shopify or WooCommerce, then a call to confirm the order and address, then hold or cancel the unverified order before it ships, plus a prepaid nudge. Inferred from the vendor pages above.

**Education / coaching (admissions)**
- Amity University: 70% connectivity and 2x form-fill conversions during peak admissions. Aakash/ANTHE (scholarship-test outreach) and Classplus are also listed, without numbers. VENDOR-CLAIM — [SquadStack case studies](https://www.squadstack.ai/case-study); [SquadStack llms.txt](https://www.squadstack.ai/llms.txt)
- College Vidya uses LeadSquared for edtech demo booking. VENDOR-CLAIM, no outcome data — [Caller.digital](https://caller.digital/blog/voice-ai-salesforce-hubspot-leadsquared-integration-india-2026)

**NBFC / microfinance / lending collections**
- Gold-loan NBFC: ₹3.96 Cr of monthly disbursals at a 2.91% cost-to-disbursal ratio. Private bank personal loans: 66% lower CAC, 2x lead connectivity, 4,000+ disbursals a month. VENDOR-CLAIM, acquisition rather than collections — [SquadStack](https://www.squadstack.ai/case-study)
- An unnamed NBFC is claimed to have improved collections by 35%, with no methodology. VENDOR-CLAIM — [Edesy](https://edesy.in/ai-voice-assistant/case-studies/nbfc-collections)
- Collections use cases: EMI reminders, soft-bucket collections, rescheduling no-answers, and a payment-link SMS during the call. VENDOR-CLAIM — [Skit.ai](https://skit.ai/resource/blog/why-nbfcs-need-voice-ai-to-create-differentiated-customer-experiences/)
- Compliance layers vendors cite: the RBI Fair Practices Code, the RBI Digital Lending Guidelines, the DPDP Act 2023 and TRAI DLT. Scaled deployments may count as "material outsourcing". VENDOR-CLAIM, not checked against RBI circulars — [Caller.digital](https://caller.digital/blog/rbi-questions-ai-voice-bot-collections-nbfc-india)

**Insurance renewals**
- A top-3 general insurer's two-wheeler renewals: 56% OpEx saved across a ₹360.9 Cr portfolio. VENDOR-CLAIM — [Gnani.ai](https://www.gnani.ai/resources/case-studies/leading-general--insurance-renewal365-2w-renewals)
- A leading general insurer: 85% connectivity and 60% lower renewal costs. VENDOR-CLAIM — [SquadStack](https://www.squadstack.ai/case-study/success-story-with-leading-general-insurer)
- Persistency uplift of 12–22% from renewal calls timed 60, 30 and 7 days before expiry. VENDOR-CLAIM — [Convin](https://convin.ai/blog/renewal-insurance)

**Automobile dealers / OEMs**
- A global automotive OEM: 3.2x buyer details captured and 3.9x test drives booked from website leads. A two-wheeler OEM recovered 15K leads in 6 weeks, with 80% intent captured. VENDOR-CLAIM, OEM-level, not dealer-level — [SquadStack](https://www.squadstack.ai/case-study)
- Mahindra runs test-drive booking across Meta click-to-WhatsApp, its website and voice AI (the case study is password-protected, so outcomes could not be checked). VENDOR-CLAIM — [LimeChat](https://www.limechat.ai/case-study/how-mahindra-runs-its-test-booking-journey-across-meta-ctwa-website-and-voice-ai)
- Haptik frames test-drive booking as a callback, a WhatsApp thread, a missed confirmation and then a no-show. VENDOR-CLAIM — [Haptik](https://www.haptik.ai/blog/ai-voice-agents-for-automotive)

**Clinics / hospitals**
- A global systematic review of 105 studies found an average outpatient no-show rate of 23%, ranging from 13.2% in Oceania to 43.0% in Africa. ACADEMIC, not India-specific — [Dantas 2018 ref](https://www.textbookofdigitalhealth.com/references/dantas2018noshows.html)
- An Indian tertiary-hospital OPD study (2024) on missed online-booked appointments exists, but its rate was not retrieved. — [IJCMPH](https://www.ijcmph.com/index.php/ijcmph/article/download/15981/9477/81235)
- Vendor blogs give 25–35% Indian no-show rates ("32% private-hospital median") with no methodology. VENDOR-CLAIM, unverified — [Caller.digital](https://caller.digital/blog/hospital-no-show-reduction-india-sms-vs-voice-ai)

**Other named Indian outcomes (adjacent, useful as proof patterns)**
- Eureka Forbes: 90% connectivity, 30% more conversions. IndiaMART: 20% higher conversions. redBus: multilingual feedback calls, 80% more feedback collected at 70% lower cost. VENDOR-CLAIM — [SquadStack](https://www.squadstack.ai/case-study)

### Inferences
- The verticals with the clearest ROI (rupees recovered or saved per call) are COD/RTO, collections, renewals and lead-to-visit. These are also the ones where vendors publish numbers. Clinics, hospitality and local services have no Indian proof points, so Calevate would need its own pilots to show proof there.
- "Connectivity" of 70–90% (SquadStack) is likely a connect rate on opted-in or warm leads, not cold calls. That fits Calevate's instant new-lead calling better than cold outbound.
- Anarock's 30% after-hours share supports the inbound receptionist and instant call-back pitch for real estate.

### Gaps
- Hotels and restaurants (reservations) and local services: no Indian case study or data found.
- Auto dealer service reminders: no Indian outcome data found.
- No independent or audited figure for any vertical. The Indian OPD no-show rate is UNKNOWN (paper not retrieved).
- Telugu or AP/Telangana-specific deployments: none found.

## Human telecaller cost and AI price comparison

### Takeaway
An Indian telecaller earns about ₹1–3.5 lakh a year, and AmbitionBox puts most entry roles near ₹0.9–2.2 lakh. Inc42 puts the cost of a human calling operation at about ₹7–8/min before hiring, training and attrition. Self-serve AI is about ₹5.5/min, and enterprise deals run as low as ₹1.75–2/min. Calevate's ₹4.50–6.00/min sits within the self-serve band, so it is not a discount offer.

### Cited Findings
- AmbitionBox: ₹1–3.5 lakh a year for under 1 to 4 years of experience (19.4k salaries). Company pages show ₹0.9–3.0 lakh (AR Sales, take-home ₹12.2–13.5k a month) and ₹0.9–2.2 lakh (Sigma Outsourcing). JOB-SITE, some figures are estimates — [AmbitionBox](https://www.ambitionbox.com/profile/telecaller-salary); [AR Sales](https://www.ambitionbox.com/salaries/ar-sales-salaries/telecaller)
- Human calling operations cost about ₹7–8/min, excluding hiring, training and attrition. Self-serve voice AI is about ₹5.5/min, and enterprise commitments go as low as ₹1.75–2/min (Bolna). Per-minute billing is dominant, and hybrid usage-plus-outcome pricing is emerging. PRESS (Inc42, 15 Jul 2026) — [Inc42](https://inc42.com/features/the-unit-economics-of-indias-voice-ai-boom/)
- Competitor list prices (VENDOR-PUBLISHED): Sarvam ₹3.50/min pay-as-you-go with no monthly fee, ex-GST; Ringg ₹6/min in India; Bolti ₹6/min with a 50-minute free trial; CallMissed ₹4/5/6 per min with telephony extra. A guide puts effective cost at ₹6–25/min after platform fees, telephony and connect-rate losses. — [Sarvam](https://docs.sarvam.ai/voice-agents/pricing); [Ringg](https://www.ringg.ai/ai-voice-agent-pricing); [CallMissed](https://www.callmissed.com/blog/twilio-alternatives-callmissed-vs-costs-india); [ecorpit](https://ecorpit.com/ecorpit-ai-voice-agent-development-service-india-2026/)
- SquadStack has launched revenue-linked pricing for its voice AI sales agents. PRESS — [CXOToday](https://cxotoday.com/media-coverage/squadstack-ai-launches-revenue-linked-pricing-model-for-voice-ai-sales-agents/)
- BPO and call-centre attrition is commonly cited at 30–50% in India, but the sources are mostly a decade or more old, and none is specific to telecallers. — [Kingston/Aston paper](https://eprints.kingston.ac.uk/53984); [Voice&Data](https://www.voicendata.com/people-play-key-productivity-enhancement-bpo)

### Inferences
- At ₹15k a month take-home (about ₹18–20k loaded), a telecaller making 4–5 talk-hours a day for 25 days gives roughly 6,000–7,500 talk-minutes, about ₹2.5–3.3 per talk-minute in salary alone. This is my arithmetic from the AmbitionBox take-home figure, not a sourced number. It is below Calevate's ₹4.50–6.00 rate. So the pitch has to rest on speed-to-lead, 24x7 coverage, burst capacity, consistency and no attrition, not on raw cost per minute. Inc42's ₹7–8/min suggests fully loaded operations cost more than salary alone.

### Gaps
- No current (2025–26) Naukri or Indeed telecaller salary figures split by Tier 1 and Tier 2 city were retrieved. No recent telecaller-specific attrition figure was found.
- Exotel and Ozonetel AI per-minute rates: UNKNOWN (not published in the results).

## Speed-to-lead, missed calls and answer rates in India

### Takeaway
No Indian primary study of lead response time or answer rates for unknown numbers was found. The widely quoted "21x within 5 minutes" figure is US research (MIT/InsideSales), and the original was not checked. Indians receive heavy spam: 4,168 crore spam calls in 2025, per Truecaller. Trust in 140/1600-series numbers is reported to be low, which supports calling leads back on the expected business number, fast.

### Cited Findings
- Truecaller's 2025 India insights: 4,168 crore spam calls received, 1,189 crore blocked. PRESS — [Mobigyaan](https://www.mobigyaan.com/truecaller-4168-crore-spam-calls-india-2025)
- India is ranked 5th most spammed country, with 66% spam intensity (2026 report). PRESS — [ETV Bharat](https://www.etvbharat.com/en/technology/india-ranked-fifth-most-spammed-country-in-the-world-truecaller-report-reveals-enn26050604266)
- Truecaller argues that TRAI's restrictions on caller ID for business numbers caused a surge in unanswered calls, and that people stopped answering 140/1600 numbers. This is the company's allegation — [LatestLY](https://www.latestly.com/technology/why-truecaller-claims-trais-whitelisting-is-behind-the-surge-in-spam-calls-7509211.html/amp)
- The 5-minute speed-to-lead figure ("21x more likely to qualify than at 30 minutes") is US-origin and repeated by vendors. NOT VERIFIED against the original — [Sell.do](https://www.sell.do/blog/speed-to-lead-real-estate-2026)

### Inferences
- The 70–90% "connectivity" vendor claims (above) are the only India answer-rate proxies, and they come from warm or opted-in lead lists.

### Gaps
- Answer rate for unknown numbers in India: UNKNOWN. Best calling times in India: UNKNOWN (no source found). Missed-call rates for Indian SMBs: UNKNOWN. Response-time data from Indian portals (99acres, MagicBricks): not found.

## SMB buyer journey in India

### Takeaway
The only credible survey data (Capterra India) shows reviews are the top influence, at 45% against 40% globally, and long purchase cycles of about 6 months, but that is not SMB-specific. Figures on WhatsApp, YouTube, resellers or CAs, GST, UPI and regional-language UI were not found from credible sources.

### Cited Findings
- 45% of Indian decision-makers rank customer reviews as the most influential source when shortlisting software (global average 40%). Indian companies take about 6 months to finalise a purchase. SURVEY (Capterra, Feb 2025, sample size not stated) — [Capterra India](https://capterra.in/blog/7613/software-purchasing-process-2025)
- 89% of Indian software buyers expect to spend at least 5% more in 2025. SURVEY — [Capterra India](https://www.capterra.in/blog/7604/india-software-spending-rise-tech-trends)
- 79% regret some tech purchases made in the past 18 months. SURVEY (2024) — [Capterra India](https://www.capterra.in/blog/4303/software-buying-trends-buyers-regret)
- "78% of Indian SMBs use WhatsApp for business": the source labels it an industry estimate, not verified — [Hyperleap](https://hyperleap.ai/blog/whatsapp-statistics-india-2026)
- Trial norms seen in competitor pricing: free minutes (Bolti, 50 min) and no monthly fee (Sarvam pay-as-you-go). VENDOR-PUBLISHED — [Sarvam](https://docs.sarvam.ai/voice-agents/pricing)

### Inferences
- Review-led shortlisting plus regret aversion suggests that visible proof (recordings, named local references) and a no-commitment pay-as-you-go trial matter more than feature lists.

### Gaps
- No credible data found on the role of YouTube, WhatsApp, resellers or agencies, or CAs in SMB software discovery; on UPI vs card payment preference; on GST-invoice expectations; or on demand for a Telugu or Hindi UI. All are UNKNOWN and need primary interviews or a different source search.
