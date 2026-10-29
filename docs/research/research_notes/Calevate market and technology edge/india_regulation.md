# Indian regulation of AI voice calling, messaging and customer data (as of 30 Oct 2026), and compliance as product features

Not legal advice. This is research notes for a report writer. Read date for every URL below is 30 Oct 2026 unless stated otherwise. Status labels used: **IN FORCE**, **NOTIFIED, NOT YET IN FORCE**, **DRAFT/PROPOSED**, **UNKNOWN**.

Primary texts read in full text this session (extracted locally from the official PDFs):
- TRAI, *TCCCPR (Second Amendment) Regulations, 2025 (1 of 2025)*, dated 12 Feb 2025 — https://trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf
- TRAI, *TCCCPR (Third Amendment) Regulations, 2026 (05 of 2026)*, dated 18 Sep 2026, with its Explanatory Memorandum — https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf
- PIB backgrounder, *DPDP Rules, 2025 Notified*, 17 Nov 2025 — https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf

Everything else is from secondary sources (law-firm notes, news, vendor blogs) and is labelled as such.

## 1. TRAI TCCCPR 2018 and the 2025 and 2026 amendments

### Takeaway
The TCCCPR was amended twice: in Feb 2025 (in force Mar/Apr 2025) and again on 18 Sep 2026 (phasing in 18 Oct, 17 Nov and 17 Dec 2026). The 2026 Third Amendment matters most for an AI voice platform. It defines "A2P calls" to include **artificial voice technologies**. From about **17 Nov 2026**, every sender must declare its A2P calls and CLI ranges to its originating operator in advance, and an undeclared A2P call is treated as UCC. It also cuts the suspension trigger to three complaints when AI spam detection agrees, adds an appeal route for complainants, and bars call-management apps from spam-tagging 140xx, 1600xx and 1601xx numbers.

### Cited Findings
**Second Amendment 2025 (1 of 2025), dated 12 Feb 2025 — IN FORCE**
- Commencement: in force 30 days after Gazette publication. Reg 8 (complaint mechanism), reg 17, reg 20(a),(b) and reg 21(b) come in after 60 days (cl.1(3)). — [TRAI Reg 12 Feb 2025](https://trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf)
- **Promotional voice call** (cl.2(av)): any voice commercial communication with promotional content. If promotional content is mixed into any commercial call, the whole call is treated as promotional. It is delivered only where the recipient has not blocked that category, or has given explicit digital consent, which overrides the preference. — same
- **Service message or service voice call** (cl.2(bh)) has two limbs. (i) Communication to the sender's own *customer* about a product or service: warranty, recall, safety, balance alerts or delivery. No explicit consent is needed. (ii) Communication that facilitates an ongoing purchase after explicit consent. That consent lasts "seven days or as directed by the Authority". — same
- **Transactional** (cl.2(bt)): a call or SMS to the sender's customer "in response to Customer initiated transaction within thirty minutes of the transaction" (OTP, transaction alerts, refunds). No consent is needed. — same
- Consent "shall not extend beyond duration / discharge of the contract" (proviso to cl.2(ah)). — same
- **UCC** (cl.2(bw)) excludes transactional, service and government communications. However, any commercial communication by a sender **not registered** with an access provider is UCC, and so is any call made to deceive. — same
- **Reg 3**: commercial communication must use registered headers or number resources from the special series. An unregistered sender's telecom resources may be suspended or disconnected. — same
- **Reg 4 (2025 text)**: "Every Sender shall notify the Originating Access Provider, in advance, about the use of Auto Dialer or Robo-Calls as well as the intended objective of such calls in writing." Reg 4 was replaced again in 2026 (below). — same
- **Enforcement against senders** (reg 25 as substituted) applies to promotional calls made from transactional or service series. If five or more unique recipients complain within ten days, the outgoing services are suspended and an investigation follows. On a first violation, all of the sender's resources, including PRI/SIP, are barred across all operators for **15 days**. On a second violation, all resources are disconnected for **one year**, the sender is blacklisted and its devices are blocked for one year, though one number may be retained. — same
- **Complaint window**: a customer must complain within **seven days** of receiving the communication (reg 23 proviso; reg 25(3)). — same
- **Re-consent cool-off** (Schedule I, item 2(2)(g)): after a customer revokes consent, the sender may re-acquire it only after **90 days**. Consent-seeking messages must come from short code **127xxx** and must name the principal entity or brand and the scope. Customers can opt out of all consent-seeking messages (entries (h)–(k)). — same
- **Preference register categories** (Schedule II): opt-out via 1909 by IVR, SMS or USSD. The options are FULLY BLOCK (0), BLOCK PROMO (50), and eight categories: 1 Banking, Insurance and Financial; 2 Real Estate; 3 Education; 4 Health; 5 Consumer goods and automobiles; 6 Communication, Broadcasting, Entertainment and IT; 7 Tourism and Leisure; 8 Food and Beverages. **FULLY BLOCK also blocks service communications that need explicit consent** (Note 3). — same
- **Financial disincentives (FD) fall on access providers, not senders** (regs 27–28). The amounts are ₹1,000 per count of complaint wrongly declared invalid, ₹5,000 per wrong registration, and ₹10,000 per repeat wrong representation decision. Misreporting costs ₹2 lakh for the first instance, ₹5 lakh for the second consecutive and ₹10 lakh for each one after. Reg 28A caps the total at **₹50 lakh per calendar month per LSA**. — same. The "₹2/5/10 lakh" figures often quoted as "penalties for UCC" are these operator misreporting FDs, not sender fines. — [Saikrishna & Associates](https://www.saikrishnaassociates.com/strengthening-consumer-protection-by-trai-amendment-to-the-tcccpr/) (secondary, consistent with the text)
- Restoration after blacklisting: ₹5,000 per resource, capped at ₹5 lakh, and each DID on a PRI/SIP trunk counts as a separate resource (reg 29). — [TRAI Reg 12 Feb 2025](https://trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf)
- **Reg 34A (2025)** bars call-management apps from blanket blocking or spam-tagging designated commercial series. — same

**Third Amendment 2026 (05 of 2026), dated 18 Sep 2026 — NOTIFIED, phasing in**
- Commencement (cl.1(3)): most provisions take effect 30 days after publication (≈18 Oct 2026). **Reg 4, 6, 8(a) and 18** take effect after 60 days (≈17 Nov 2026). The Annexure items take effect after 90 days (≈17 Dec 2026). The exact Gazette publication date was not separately confirmed; the dates are computed from 18 Sep. — [TRAI Reg 18 Sep 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf); the same 30/60/90 reading appears in [thetelephony.co](https://www.thetelephony.co/india/blog/tcccpr-third-amendment-dates) (secondary)
- **New definition cl.2(ea), "A2P call"**: "a voice call that is initiated by an application, software system, or automated platform without direct human dialling … including using autodialling, robo-calls and/or pre-recorded/artificial voice technologies". — [TRAI Reg 18 Sep 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)
- **New reg 4, "Intimation regarding use of A2P calls"** (60-day item, ≈17 Nov 2026): every sender must declare its A2P calls to the OAP in advance, with the CLI ranges it will use, and the declaration is recorded on DLT. "Any such call made by a Sender without prior declaration to the OAP, shall be treated as Unsolicited commercial communication". — same
- **Consent** (cl.2(k)) is redefined as voluntary permission, explicit or inferred, and Explanation 3 says nothing in the regulations exempts a sender from the DPDP Act 2023. **Explicit consent** (cl.2(y)) is consent verified and recorded by the Consent Registrar, or obtained by verifiable means and *subsequently registered in the Consent Register*. — same
- **Relationship** (cl.2(bb)) now covers: (i) an existing business relationship; (ii) an inquiry by the recipient within the **preceding seven days**, made in writing or digitally and kept "in a verifiable form by the Sender"; (iii) an application by the recipient within the preceding **three months**. — same
- **Service call** (cl.2(bh)) now explicitly includes OTPs for authentication. For limb (ii), explicit consent is "valid for a period of seven days or until revoked … and it may be renewed at the instance of the customer for an additional period of seven days at a time". — same
- **New reg 21A**: each terminating operator runs an AI/ML "UCC_Detect" system that flags "Suspected high probability UCC CLI" and shares it on DLT within two hours. The OAP notifies the sender by SMS or email, maps the sender's KYC across all operators, and acts if five or more of the sender's CLIs are flagged in ten days. CLIs from the **140xx, 1600xx and 1601xx** series must not be shown to recipients as "Suspected UCC/spam", and a sender can contest a flag. — same
- **Complaint threshold lowered**: suspension follows **three or more complaints from unique recipients in ten days across operators, plus an AI flag on any of the sender's CLIs**, or five or more complaints without one (reg 25 as substituted, sub-reg (5)(d)(i)). — same; also reported by [Cavalier](https://www.cavalier.in/cds-ota-current-affairs/2026-09-18/trai-ucc-tccpr-third-amendment-2026) (secondary)
- **Appeal**: a complainant can appeal to the Appellate Authority (under the Telecom Consumers Complaint Redressal Regulations 2012) within 15 days after an unsatisfactory resolution, or after 15 days with no resolution (reg 24/25 changes). Operators must keep **two years** of complaint history per complainant and per sender. — [TRAI Reg 18 Sep 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)
- **Misused-header duty on senders**: on notice, the sender must reset credentials within three business days and file a police complaint within three business days. — same
- **New reg 34A (2026)**: no call-management app or phone dialler may tag, block or filter calls from designated commercial or government series, or treat them differently. Users may still block calls on their own devices. Apps may offer "report spam" only if the report goes to the operators' DLT platform. — same
- **New reg 35A, the A2P termination charge** (60-day item): the terminating operator may charge the originating one up to **₹0.05 per minute** for A2P calls. A2P calls from the **140xx, 1600xx and 1601xx** series are exempt. — same
- Reg 3 proviso: TRAI may classify senders and set different criteria per class, which the Explanatory Memorandum ties to exempting small BFSI players from mandatory 1600. A "Regulatory Sandbox" definition is added. — same

**Digital Consent Acquisition (DCA) / consent registry — PILOT; national rollout UNKNOWN**
- TRAI's Direction of 2 Jun 2023 requires access providers to build DCA. Without it, consents held by each principal entity cannot be verified. — [PIB](https://www.pib.gov.in/PressReleasePage.aspx?PRID=1975372&reg=3&lang=2)
- A TRAI–RBI pilot was announced around 10 Dec 2025 with nine telecom operators and eleven banks (SBI, PNB, Axis, HDFC, ICICI and others). It uploads legacy consents, and customers get an SMS so they can review or revoke them. — [Legal500](https://www.legal500.com/intelligence/india/media-telecoms-it-entertainment/trai-rbi-digital-consent-acquisition-pilot-closing-the-legacy-consent-gap-under-tcccpr-2018); [PIB](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2201612&reg=48&lang=2)
- The pilot was expected to complete by Feb 2026. — [Medianama, Oct 2025](https://www.medianama.com/2025/10/223-digital-consent-platform-trai-rbi-february-2026/)

**Calling hours (TRAI)**
- Neither TRAI text I read fixes calling hours for service or transactional calls. Preferences can be set by "time band and day types" (Schedule II Note 3). Vendor blogs give conflicting hours (10am–7pm vs 9am–9pm). — [TRAI Reg 12 Feb 2025](https://trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf); conflicting vendor claims at [Rootle](https://rootle.ai/blog/the-february-2025-trai-amendment-voice-ai-compliance/), [Frejun](https://frejun.com/trai-compliance-call-centers/)

**Blockchain DLT**
- DLT is the operational backbone in both amendments: header and template registration, DL-Complaints recorded "in non-repudiable and immutable manner", A2P declarations recorded on DLT, and AI flags shared over DLT. — [TRAI Reg 18 Sep 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)

### Inferences
- **Calevate's AI agents make "A2P calls" by definition.** From ≈17 Nov 2026, each outbound sender (each client, or Calevate as telemarketer, depending on who the OAP registers) must have declared its A2P CLI ranges in advance, or every such call is UCC. This is a concrete onboarding gate the product should enforce. Who files the declaration on ThinnestAI-originated calls is a gap (see Gaps).
- The "no cold calls" pledge lines up with the service-call limb (i), which covers calls to the sender's own customers. Calls prompted by an inquiry are "relationship" calls only within **seven days**, and only if the inquiry is stored in verifiable form. The consent ledger should record the inquiry evidence and enforce the seven-day and three-month windows.
- Any promotional sentence in a service call turns the whole call promotional. Scripts need a promo-content lint.
- The new three-complaint-plus-AI-flag trigger makes complaint *velocity* monitoring worth building: one bad campaign can suspend a client's trunks for 15 days.

### Gaps
- The exact Gazette publication date of the Third Amendment is unconfirmed; the 30/60/90-day dates above are computed from 18 Sep 2026.
- I could not read the Annexure (90-day items) in detail, so its contents are not summarised here.
- Whether DCA has gone national beyond the RBI bank pilot is UNKNOWN; no primary source was found.
- No primary source sets TRAI calling hours for service calls. UNKNOWN; do not quote 9–9 or 10–7.
- Whether a ThinnestAI-hosted number used by a Calevate client counts as "declared A2P" under the client's KYC or ThinnestAI's is UNKNOWN and should go to ThinnestAI and the OAP.

## 2. DoT/TRAI 1600-series mandate, extension to other sectors (1601xx), and CNAP

### Takeaway
1600xx is mandatory for transactional and service calls by RBI-, SEBI- and PFRDA-regulated entities (deadlines Jan–Mar 2026) and for government. A new **1601xx** series for other sectors started operating with a TRAI Direction of **10 Aug 2026**, phase 1 covering **utilities, logistics and courier**. CNAP was directed to go live from **1 Nov 2026** on 4G and later networks. That date comes from secondary sources and I did not see the DoT circular.

### Cited Findings
- TRAI's Explanatory Memorandum (Sep 2026) says 140xx is mandated for promotional calls and 1600 for transactional and service calls by BFSI and government-to-citizen calls. TRAI decided not to extend 1600 to other sectors. Instead "a separate 1601xx series has been recently allotted by the Department of Telecommunications for transactional and service calls by other sectors", introduced in phases, with "a Direction on 10th August, 2026 for first phase … covering Utilities, Logistics and Courier services". Small BFSI players may be exempted from mandatory 1600 under the new reg 3 classification power. — [TRAI Reg 18 Sep 2026, Explanatory Memorandum](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)
- The 1600 deadlines (TRAI Direction, Nov 2025) are: commercial banks **1 Jan 2026**; large NBFCs, payments banks and small finance banks **1 Feb 2026**; mutual funds and AMCs **15 Feb 2026**; qualified stockbrokers **15 Mar 2026**. Insurance is "under discussion with IRDAI, and will be notified subsequently". — [PIB PRID 2191647](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2191647&reg=48&lang=2) (403 on fetch; quoted via search snippet), [Business Standard](https://www.business-standard.com/industry/news/trai-sets-deadlines-bfsi-adopt-1600-series-official-calls-125111900858_1.html)
- A2P calls from 140xx, 1600xx and 1601xx are exempt from the new ₹0.05/min A2P termination charge, and cannot be shown as spam. — [TRAI Reg 18 Sep 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)
- **CNAP**: reports say a DoT circular of 13 Oct 2026 directs all access providers to implement CNAP from 1 Nov 2026 on 4G and newer networks, showing the KYC-registered name by default. Businesses can apply for a verified preferred name. The earlier 31 Mar 2026 target was missed. — [Telangana Today](https://telanganatoday.com/mobile-users-to-see-callers-names-under-new-cnap-framework-from-november-1), [National Herald](https://www.nationalheraldindia.com/national/department-of-telecommunications-directs-telecom-operators-to-roll-out-caller-name-display-service-from-1-november), [Business Standard (earlier March 2026 target)](https://www.business-standard.com/industry/news/cnap-service-nationwide-rollout-by-march-2026-dot-trai-telecom-125102901190_1.html)

### Inferences
- If a Calevate client is a courier, logistics firm or utility, its service calls may need to move to 1601xx under the 10 Aug 2026 Direction. The product should ask for the client's sector at KYC and show which series applies.
- With CNAP, the caller's **KYC name** shows on the callee's phone. A client calling from a number held in someone else's name (for example, the platform's) will show the wrong name. Business-name CNAP registration is a trust feature, and a likely question for ThinnestAI.

### Gaps
- I did not read the 10 Aug 2026 1601xx Direction itself (its deadlines and the later sector phases are UNKNOWN), or the DoT CNAP circular of 13 Oct 2026.
- The final date for insurance moving to 1600 is UNKNOWN.
- Whether any 2026 deadline was extended is UNKNOWN.

## 3. DPDP Act 2023 and DPDP Rules 2025

### Takeaway
The DPDP Rules were notified on 13/14 Nov 2025 with an 18-month phase-in. The Board is in force now, consent-manager registration opens around 13 Nov 2026, and the substantive fiduciary duties (notice, security, breach intimation, erasure, rights) begin around 13 May 2027. MeitY consulted in early 2026 on cutting this to 12 months, and I found no notification confirming that.

### Cited Findings
- PIB says the Rules were notified on **14 November 2025** with "an eighteen-month period for phased compliance". Consent notices must be separate, clear and purpose-specific. Consent managers must be India-incorporated companies. — [PIB backgrounder 17 Nov 2025](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf)
- Rights requests (access, correction, update, erasure, nomination) must be answered within **90 days**. A contact for the DPO or designated officer must be displayed. Children's data needs verifiable parental consent except for health, education and real-time safety. Significant Data Fiduciaries need independent audits and DPIAs. — same
- **Penalties (Act Schedule)**: up to **₹250 crore** for failing reasonable security safeguards; up to **₹200 crore** each for not notifying a breach and for children's-data violations; up to **₹50 crore** for any other violation. Appeals go to TDSAT. — same
- Phasing (secondary, consistent across sources): Rules 1, 2 and 17–21 (the Board) took effect at notification; Rule 4 (consent manager registration) on **13 Nov 2026**; the remaining fiduciary obligations on **13 May 2027**. Breach intimation (Rule 7) is "without delay" to individuals and the Board, plus a detailed report to the Board within **72 hours** (the Board can extend this). — [cy5.io](https://www.cy5.io/blog/dpdp-rules-2025-complete-compliance-guide-cloud-security/), [Scrut](https://www.scrut.io/post/dpdp-rules), [bitscore](https://www.bitscore.in/tools/dpdp-commencement/breach-notification-72-hours)
- CERT-In's separate **6-hour** cyber-incident reporting runs in parallel. — [bitscore](https://www.bitscore.in/tools/dpdp-commencement/breach-notification-72-hours) (secondary)
- **Proposed compression (DRAFT/PROPOSED)**: MeitY sought views in Jan–Feb 2026 on cutting the window from 18 to 12 months, which would make 13 Nov 2026 the deadline. Sources conflict on details. — [Storyboard18](https://www.storyboard18.com/digital/meity-seeks-industry-views-on-fast-tracking-dpdp-act-rollout-proposes-12-month-compliance-timeline-88332.htm), [S.S. Rana](https://ssrana.in/articles/meity-plans-to-cut-short-dpdp-compliance-timeline-and-notify-cross-border-restrictions-for-sdfs/), [Takshashila](https://takshashila.org.in/content/blogs/20260126-meity-considers-reducing-dpdpa-compliance-timelines.html)
- TRAI's 2026 definition of consent says TCCCPR does not exempt senders from DPDP. — [TRAI Reg 18 Sep 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)

### Inferences
- The SMB client is the **Data Fiduciary** for its callers' data, and Calevate is a **Data Processor** (and a fiduciary for its own account data). The duties land on SMBs that have no DPO, no notice text and no breach process. A platform that ships these ready-made is selling compliance.
- Retention and erasure rules (for example, erasure after a period of inactivity with advance notice, and one-year log retention) are commonly reported in commentary on the Rules. I did not verify them against the Rules text, so they are not stated as fact here.

### Gaps
- I did not read the Rules' Gazette text; Rule numbers and the 72-hour figure come from secondary sources.
- Whether the 18-month window was shortened is UNKNOWN. If it was, the obligations may bind from 13 Nov 2026 rather than 13 May 2027, so this must be checked on meity.gov.in / egazette before quoting a date to clients.
- Cross-border transfer restrictions (the government may notify restricted countries) and any SDF localisation lists are UNKNOWN as of Oct 2026.

## 4. AI-specific rules: MeitY AI governance, synthetic-voice / deepfake rules, AI disclosure on calls

### Takeaway
No Indian law I found requires a voice agent to tell callers it is an AI. The binding AI-content rule is the IT Rules amendment of 10 Feb 2026 (in force 20 Feb 2026) on "synthetically generated information": labelling plus metadata or provenance, with audio carrying a prefixed disclosure. It binds **intermediaries**. TRAI now names "artificial voice technologies" inside A2P calls, which means operator declaration, not caller disclosure. The MeitY AI Governance Guidelines (Nov 2025) are advisory.

### Cited Findings
- MeitY notified the IT (Intermediary Guidelines and Digital Media Ethics Code) Amendment Rules 2026 on **10 Feb 2026**, effective **20 Feb 2026**. They define SGI (Rule 2(1)(wa)) as audio, visual or audio-visual content created or altered by a computer resource that appears real or could be mistaken for a real person or event. Rule 3(3) makes intermediaries that enable SGI label it prominently and embed permanent metadata or a unique identifier. Rule 4(1A) makes significant social media intermediaries take user declarations and verify them. Takedown of some unlawful content is cut to three hours. — [Medianama](https://www.medianama.com/2026/02/223-meity-amendments-it-rules-synthetic-media-deepfakes/), [Chandhiok & Mahajan](https://chandhiok.com/insights/cm-e-alert-ministry-of-electronics-and-information-technology-notifies-the-information-technology-intermediary-guidelines-and-digital-media-ethics-code-amendment-rules-2026), [Legal500](https://www.legal500.com/intelligence/india/media-telecoms-it-entertainment/2026-it-rules-amendments-ai-content-labelling-and-intermediary-obligations)
- Synthetic audio reportedly must carry "a prominently prefixed audio disclosure". This is reported from a MeitY FAQ and was not verified against the rule text. — search-result summary of vendor sources ([caller.digital](https://caller.digital/blog/ai-voice-deepfake-fraud-caller-trust-india-2026)); treat as REPORTED.
- IFF criticises the 2026 rules as compelled speech that relies on unreliable detection. — [IFF](https://internetfreedom.in/it-intermediary-amendment-rules-2026-contradict-their-purpose/)
- MeitY released the India AI Governance Guidelines in Nov 2025. They are advisory and principle-based: transparency, accountability, redress and voluntary commitments. — [IAPP](https://iapp.org/news/a/notes-from-the-asia-pacific-region-india-releases-dpdpa-rules-ai-governance-guidelines); advisory status per [Rootle](https://rootle.ai/blog/voice-ai-compliance-in-india-beyond-trai/) (vendor)
- TRAI defines A2P calls to include "pre-recorded/artificial voice technologies" and requires advance declaration to the OAP. — [TRAI Reg 18 Sep 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)
- A call made "to deceive the recipient" is UCC (2025 cl.2(bw) proviso), which bears on cloned-voice impersonation. — [TRAI Reg 12 Feb 2025](https://trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf)

### Inferences
- Calevate's server-enforced truthful answer ("yes, I am an AI; yes, the call is recorded"), together with the opt-in volunteered disclosures, goes beyond Indian law as far as I found. It is a selling point, not a legal minimum, and should be marketed carefully as "beyond what the law requires" rather than "required by law".
- Whether a voice-agent platform is an "intermediary that enables SGI" under Rule 3(3) is an open legal question. Admin voice cloning with documented consent of the voice owner, plus watermark or metadata on recordings, would be defensible either way.

### Gaps
- The Gazette text of the IT Amendment Rules 2026 was not read, so whether real-time phone audio counts as SGI that an intermediary "hosts" is UNKNOWN.
- No Indian statute or rule specifically on voice-cloning consent was found. UNKNOWN; the personality-rights case law in Delhi HC celebrity suits was not researched here.
- The content of the MeitY AI Governance Guidelines was not read in primary form.

## 5. Sectoral: RBI recovery calls, IRDAI, SEBI, telemedicine

### Takeaway
The RBI's 8am–7pm recovery-call window is long-standing and is being re-codified in the 2025–26 "Responsible Business Conduct" directions. The effective dates differ by lender class and are not confirmed from rbi.org.in here. IRDAI, SEBI and telemedicine were not researched to primary level.

### Cited Findings
- The RBI has long barred recovery agents from calling borrowers before 8am or after 7pm. — [Deccan Herald](https://www.deccanherald.com/business/rbi-directs-loan-recovery-agents-not-to-intimidate-borrowers-no-calling-before-8am-after-7pm-1135618.html)
- The draft *Commercial Banks – Responsible Business Conduct Amendment Directions, 2026* (comments due 31 May 2026; intended start 1 Oct 2026) restates 8am–7pm. It defines recovery agents to include Business Correspondents, bars contact on bereavement and similar occasions, and requires call recording kept at least six months. Sources conflict on the effective date: one says 1 Jan 2027, another cites a "Fourth Amendment" of 6 Aug 2026. — [Upstox](https://upstox.com/news/business-news/financial-regulations/rbi-proposes-overhaul-of-loan-recovery-norms-draft-rules-ban-harassment-cap-calls-to-8am-7pm/article-189398/), [Exotel](https://exotel.com/rbi-loan-recovery-guidelines), [Corporate Professionals (NBFC draft)](https://www.corporateprofessionals.com/articles/draft-rbi-nbfc-responsible-business-conduct-directions-2026-key-amendments/)

### Inferences
- A "collections pack" should enforce an 8am–7pm IST window per callee, an occasion-sensitivity stop list, recording retention of at least six months, and no-threat or no-abuse script guardrails. Those are hard-coded behaviours an AI agent can guarantee better than humans.

### Gaps
- The final RBI direction numbers and effective dates are UNKNOWN; rbi.org.in was not read.
- IRDAI (insurance telemarketing, recording of sales calls), SEBI (investment adviser calls) and the Telemedicine Practice Guidelines 2020 (an AI agent cannot give medical advice) are not researched here and are UNKNOWN for Oct 2026.

## 6. Call recording law in India

### Takeaway
No Indian statute expressly sets a one-party or all-party consent rule for a participant recording a call. Courts have treated recording without consent as a privacy (Art. 21) problem in some contexts. A business recording customer calls processes personal data, which under DPDP needs notice and consent or a legitimate use. Announcing the recording is the safe and standard practice.

### Cited Findings
- The law does not expressly specify one- or two-party consent. Participant recording is generally treated as permissible, subject to privacy and evidence law. — [iPleaders](https://blog.ipleaders.in/is-call-recording-legal-in-india-and-admissible-in-courts/), [BNB Legal](https://bnblegal.com/article/call-recording-legal-in-india/)
- The Delhi HC held that recording calls without consent breaches privacy under Art. 21 (in a bail context). — [K&S Partners](https://ksandk.com/litigation/recording-calls-without-consent-is-a-violation-of-article-21/)
- Admissibility of electronic records now falls under s.63 of the Bharatiya Sakshya Adhiniyam 2023, and the Telecommunications Act 2023 replaced the Telegraph Act for interception. — secondary search summaries of [Mondaq](https://webiis08.mondaq.com/india/privacy-protection/1646056/call-recordings-evidentiary-value-vs-privacy-violation); TRAI's 2026 text likewise replaces Telegraph Act references (cl.2(e) of the amendment), per [TRAI Reg 18 Sep 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)

### Inferences
- An announced recording notice plus DPDP-grade notice, retention limits and erasure is defensible. Calevate's separate recording-notice toggle matches the "separate regimes" reality, but turning the notice off carries risk for the client and should come with a warning.

### Gaps
- No Supreme Court holding on business call recording was found.

## 7. Compliance-driven product features for Indian SMBs

### Takeaway
The regulation turns into a short list of automatable controls. The strongest differentiators for 2026–27 are A2P/CLI declaration onboarding (TRAI from ≈17 Nov 2026), series selection by sector (140/1600/1601), consent evidence with TRAI's seven-day, three-month and 90-day clocks, complaint-velocity alarms tied to the new three-complaint trigger, and a DPDP kit (notice, 90-day rights desk, breach playbook) ready before 13 May 2027 (or 13 Nov 2026 if compressed).

### Cited Findings (each feature is tied to the rule cited above)
1. **A2P declaration wizard**: collect and record the client's declaration of A2P use and CLI ranges to its OAP, and block dialling from an undeclared CLI (2026 reg 4). — [TRAI Reg 18 Sep 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)
2. **Number-series advisor**: map the KYC'd sector to the series. BFSI and government use 1600xx; utilities, logistics and courier use 1601xx (phase 1, 10 Aug 2026); promotional calls use 140xx, which Calevate refuses under its pledge. — same; [PIB 1600](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2191647&reg=48&lang=2)
3. **Call-purpose classifier and promo lint**: check every script and campaign as transactional (within 30 minutes of a customer action), service limb (i), service limb (ii) (explicit consent, seven days, renewable), or relationship (inquiry within seven days, application within three months). Refuse mixed promotional content, because mixing makes the whole call promotional. — [TRAI 2025](https://trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf), [TRAI 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)
4. **Consent evidence vault**: store the timestamped, verifiable inquiry or consent artefact (form, WhatsApp, IVR keypress, call transcript snippet) with auto-expiry at seven days, three months or contract end, a 90-day re-consent lockout after revocation, and an export in Consent Register format once DCA is national. — same
5. **Preference and DND scrub at dial time**: check the 1909 preference register including category codes 1–8, FULLY BLOCK (which also blocks consented service calls) and BLOCK PROMO, plus the global and tenant DNC lists, at each dial. — [TRAI 2025 Schedule II](https://trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf)
6. **Complaint-velocity alarm and auto-pause**: watch complaints per unique recipient over a rolling ten days and any operator spam flag on a CLI. Auto-pause campaigns before the three-complaint-plus-AI-flag threshold, because the first violation means a 15-day bar on all resources and the second means a one-year disconnection and blacklist. — [TRAI 2026 reg 25](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)
7. **Spam-flag representation helper**: when the OAP's SMS or email says a CLI was flagged (reg 21A(2)), draft the representation with the call logs and consent evidence. — same
8. **Header-compromise runbook**: a three-business-day credential reset and police-complaint checklist (2026 amendment). — same
9. **Sector-aware calling-hours engine**: 8am–7pm IST for collections (RBI) and occasion stop-lists. TRAI service-call hours are UNKNOWN, so this should be a configurable window, not a legal claim. — [Upstox/RBI draft](https://upstox.com/news/business-news/financial-regulations/rbi-proposes-overhaul-of-loan-recovery-norms-draft-rules-ban-harassment-cap-calls-to-8am-7pm/article-189398/)
10. **DPDP kit for the SMB as fiduciary**: a generated plain-language, multilingual consent notice (Telugu and English); a 90-day rights-request desk for access, correction, erasure and nomination, with SLA timers; a published DPO or contact block; a breach playbook with "without delay" notice to individuals and the Board, a 72-hour detailed-report template and a CERT-In six-hour flag; a children's-data guard; processor DPA terms. — [PIB DPDP backgrounder](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf), [cy5.io](https://www.cy5.io/blog/dpdp-rules-2025-complete-compliance-guide-cloud-security/)
11. **Consent-manager readiness**: accept consent artefacts and withdrawals from registered consent managers once Rule 4 registration opens (≈13 Nov 2026). — [Scrut](https://www.scrut.io/post/dpdp-rules)
12. **AI and recording disclosure guarantees**: server-enforced truthful answers plus configurable opening disclosures, a "prefixed synthetic audio" option aligned to the IT Rules 2026 audio-label wording, and metadata or watermark on stored recordings. — [Medianama](https://www.medianama.com/2026/02/223-meity-amendments-it-rules-synthetic-media-deepfakes/)
13. **Voice-clone consent register**: record written consent of the voice owner before any admin clone, kept with the provenance ID. This is a protective control; no specific Indian rule was found.
14. **CNAP business-name check**: verify that the calling number's KYC name shows as the client's brand, because CNAP showed names from 1 Nov 2026 (secondary). — [Telangana Today](https://telanganatoday.com/mobile-users-to-see-callers-names-under-new-cnap-framework-from-november-1)
15. **Regulator-ready audit pack**: a per-campaign export of consent artefacts, scrub results, declared CLIs, disclosures spoken, complaints and actions. TRAI makes operators keep two years of complaint history, so clients should hold the same. — [TRAI 2026](https://www.trai.gov.in/sites/default/files/2026-09/Regulation_18092026.pdf)
16. **Retention controls**: per-tenant retention of recordings and transcripts, with sector minimums (for example, RBI's draft six-month minimum for recovery-call recordings) and DPDP maximums. — [Exotel/RBI draft](https://exotel.com/rbi-loan-recovery-guidelines)

### Inferences
- The buyer-facing message that holds up against these sources is: "we keep your numbers from getting barred, and we keep you ready for DPDP." The 15-day and one-year telecom penalties fall directly on the SMB's lines. That is more visceral to an SMB than DPDP's ₹50–250 crore ceilings, which they discount.
- Features 1, 3, 4 and 6 depend on how ThinnestAI originates calls (whose KYC the OAP holds, and which CLI series). That is an external question, not an engineering one.

### Gaps
- Who the "Sender" is for TRAI purposes when a Calevate client calls through a ThinnestAI number (client, Calevate as telemarketer, or ThinnestAI) is UNKNOWN and needs ThinnestAI's and the OAP's written answer.
- Sector packs for insurance (IRDAI), securities (SEBI) and health (telemedicine) need primary-source research that was not done here.
