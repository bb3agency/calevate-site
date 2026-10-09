# Aadhaar Offline Verification and PAN Name Verification

**Date read: 9 October 2026 (IST).** This report uses only UIDAI material, the official Gazette copy hosted by UIDAI, official UIDAI FAQs, Income Tax Department pages, and Protean’s official PAN-verification pages. Where a requested point is not expressly answered by those sources, it says **“not stated.”**

## Direct answers

| Question | Answer as of 9 October 2026 |
|---|---|
| Must a private business register as an OVSE to verify Paperless Offline e-KYC XML or Secure QR? | **Yes for Paperless Offline e-KYC.** Regulation 13A, inserted with effect from 9 December 2025, requires an entity wishing to undertake Paperless Offline e-KYC verification to apply to UIDAI for registration. **For Secure QR alone, the new registration clause does not expressly name QR Code verification**, although the Act/regulations still classify the verifier as an OVSE and impose OVSE duties. Therefore a categorical registration requirement for QR-only verification is **not stated** in regulation 13A. UIDAI’s current OVSE onboarding page broadly invites entities seeking to perform offline verification to register; applying is the risk-minimising course.[^1][^2] |
| Is approval needed? | **Yes where regulation 13A applies.** UIDAI may approve the application and register the entity after checking eligibility and submitted information.[^1] |
| Can a sole proprietorship register? | **Yes.** UIDAI’s official current application form expressly includes “☐ Proprietorship” as an entity category.[^3] |
| XML contents | Name; reference ID containing last four Aadhaar digits plus timestamp; address; photo; gender; DoB/YoB; hashed mobile; hashed email. The XML does not reveal the full Aadhaar number.[^4] |
| Secure QR on e-Aadhaar/PVC | Both carry a UIDAI-digitally-signed Secure QR with demographic information and photograph. UIDAI describes the QR payload as Ref ID, name, gender, DOB, mobile, email, address, photograph and a 2048-bit digital signature.[^5] |
| Free official PAN name check | **Yes, but it is a manual, rate-limited match service—not a free general API or name lookup.** Income Tax “Verify Your PAN” accepts PAN, claimed full name, DOB and any accessible mobile number for OTP; it checks whether the submitted details match and allows up to five PANs per mobile number per day.[^6][^7] |
| Protean service for an ordinary sole proprietor | **Not stated as eligible.** “Sole proprietor/proprietorship” is absent from Protean’s published eligibility list; registration requires ITD approval and costs ₹12,000 plus GST annually. |

## Registration and approval

### Paperless XML

The controlling post-2025 clause is regulation 13A(1):

> “An entity desirous of undertaking Aadhaar Paperless Offline e-KYC verification or Aadhaar Verifiable Credential verification through Aadhaar Application shall apply to the Authority for registration, in such form as the Authority may provide upon request made to it by such entity and on such terms and conditions as may be specified by the Authority from time to time: Provided that such entity on being registered as OVSE shall perform offline verification only for lawful purposes.”[^1]

Approval is discretionary under regulation 13A(4):

> “The Authority may, if it is satisfied that the entity is eligible as per the terms and conditions specified by the Authority, may approve the application and register the entity as OVSE.”[^1]

Thus, the older 2022 UIDAI FAQ saying “No license is required from UIDAI” has been superseded for Paperless Offline e-KYC by the 2025 amendment. That FAQ’s exact wording was:

> “Note: No license is required from UIDAI to be able to use Aadhaar offline verification.”

The amendment’s Gazette date and effective date are 9 December 2025, and UIDAI lists no later Authentication and Offline Verification amendment through the read date.[^8][^1]

### Secure QR

Regulation 13A names only “Aadhaar Paperless Offline e-KYC verification” and “Aadhaar Verifiable Credential verification through Aadhaar Application”; it does **not** name “QR Code verification.” The same consolidated regulations separately list QR Code verification as a type of offline verification, while defining OVSE as any entity desirous of undertaking offline verification.[^9]

The operative acceptance rule, regulation 16C(1), states:

> “No Offline Verification Seeking Entity shall accept Aadhaar number, in physical or electronic form (without authentication), as a proof of identity for a lawful purpose, without first verifying the digital signature of the Authority as provided in the Aadhaar secure QR Code on Aadhaar Letter or e-Aadhaar or Aadhaar Paperless Offline e-KYC, as the case may be.”[^9]

Accordingly, **a QR verifier is an OVSE and bears OVSE duties**, but whether QR-only verification triggers mandatory registration under regulation 13A is **not stated**. UIDAI’s current onboarding page is broader: “Entities seeking registration as an Offline Verification Seeking Entity (OVSE) to perform offline verification of Aadhaar number holder for lawful purpose may apply to the Authority in the prescribed application form.”[^2]

### Sole proprietorship

The official UIDAI application form’s entity-category field reads:

> “☐Central Govt. Organization ☐ State Govt. Organization ☐ PSU ☐ Private Organization ☐Partnership Firm ☐ Proprietorship ☐ NGO ☐Society/ Trust/ cooperative”[^3]

The form also requires PAN, supporting documents, a registration number or “any Other ID,” use-case details, registered domain/callback information, a Class 3 public certificate, contacts and declarations. It says a satisfactory application receives a registration certificate and unique OVSE Registration Number, initially valid for two years.

## XML contents and signature

UIDAI’s current Paperless Offline e-KYC page lists:

> “Aadhaar number holder Name”; “Download Reference Number”; “Address”; “Photo”; “Gender”; “DoB/YoB”; “Mobile Number (in hashed form)”; “Email (in hashed form)”.

UIDAI explains the masked identifier as:

> “This is a composition of last 4 digits of Aadhaar number followed by timestamp in YYYYMMDDHHMMSSmmm format.”

The XML schema shown by UIDAI contains `OfflinePaperlessKyc`, `UidData`, `Poi`, `Poa`, `Pht`, and a W3C XML Digital Signature. It specifies canonical XML 1.0, an enveloped-signature transform, `rsa-sha1` as the signature method, and SHA-256 as the digest method.

For the photo and signature, UIDAI states:

> “Pht - Photo: Is present in JP2000 format with low resolution. Standard JP2 renderers can be used to show the photo.”

> “signature - Signature: This will a 344 character long digital signature of the data present in the downloaded XML. This can be validated using the public key of UIDAI which will be present in standard signed xml.”

The ZIP is encrypted using the resident-selected Share Phrase; after extraction, the verifier parses the XML and validates UIDAI’s signature. Optional local OTP or face matching may bind the presenter to the data.

### Signing certificate

UIDAI publishes the certificates on its official **Data and Downloads → UIDAI Certificates Details → Offline e-KYC public key certificates** page:

- <https://uidai.gov.in/en/data-and-download>
- Current listed Paperless Offline e-KYC certificate: `uidai_offline_publickey_2026.cer`, expiry 3 February 2029.
- Historical Paperless Offline e-KYC and Secure QR certificates are also listed there.

UIDAI’s older FAQ links a historical certificate directly, but production code should use the certificate page/current listed certificate rather than hard-code an expired historical link.[^4]

## OVSE obligations

### Consent and notice

Aadhaar Act section 8A(2) provides:

> “Every offline verification-seeking entity shall,— (a) before performing offline verification, obtain the consent of an individual, or in the case of a child, his parent or guardian, in such manner as may be specified by regulations; and (b) ensure that the demographic information or any other information collected from the individual for offline verification is only used for the purpose of such verification.”

Section 8A(3) requires disclosure of the nature of information shared, intended uses, and alternatives. Regulation 6 requires physical or preferably electronic consent and records:

> “A requesting entity or OVSE shall obtain the consent referred to in sub-regulation (1) above in physical or preferably in electronic form and maintain logs or records of the consent obtained in the manner and form as may be specified by the Authority for this purpose.”[^9]

Regulation 5 also requires an alternative viable means of identification and says service must not be denied merely for refusal or inability to undergo offline verification, provided the person can identify through the offered alternative.[^9]

### Storage and Aadhaar-number ban

Aadhaar Act section 8A(4)(b) is categorical:

> “No offline verification-seeking entity shall— … collect, use, or store an Aadhaar number or biometric information of any individual for any purpose.”

Regulation 14A(1)(b) adds:

> “shall not collect, use or store Aadhaar number or biometric information of any individual for any purpose or share offline Aadhaar data with any other entity except in accordance with the Act and Regulations framed thereunder”.[^9]

Offline data may be stored only with consent and securely. Regulation 16A(3)-(4) states:

> “An OVSE may store, with consent of the Aadhaar number holder, offline Aadhaar data of the Aadhaar number holder, received upon Offline Verification, securely as per the guidelines issued by the Authority from time to time.”

> “The Aadhaar number holder may, at any time, revoke consent given to an OVSE for storing his/her offline Aadhaar data, and upon such revocation, the OVSE shall delete the offline Aadhaar data in a verifiable manner and provide an acknowledgement of the same to the Aadhaar number holder.”[^9]

A fixed maximum retention duration for OVSE-stored offline Aadhaar data is **not stated** in these provisions. The rule is purpose/consent limited, with verifiable deletion on revocation; logs are optional, not subject to the requesting-entity authentication-log periods.

### Optional logs

Regulation 20A permits logs only if necessary and with consent, covering the offline document, other resident-supplied data, local transaction logs, and notification details. Its strict prohibition is:

> “but shall not, in any event, store the Aadhaar number or Virtual ID of the Aadhaar number holder.”[^9]

It further states:

> “The OVSE shall not share the logs with any person other than the concerned Aadhaar number holder or for grievance redressal and resolution of disputes in accordance with the provisions of the Act. The verification logs shall not be used for any purposes other than those stated in this sub-regulation.”[^9]

### Audit and infrastructure

Regulation 21(1) provides:

> “The Authority may undertake audit of the operations, infrastructure, systems and procedures, of requesting entities, including their Sub-AUAs and Sub-KUAs, Authentication Service Agencies and Offline Verification Seeking Entities, either by itself or through audit agencies appointed by it, to ensure that such entities are acting in compliance with the Act, rules, regulations, policies, procedures, guidelines issued by the Authority.”[^9]

The entity must cooperate and provide complete access to relevant procedures, records and information, and “The cost of audits shall be borne by the concerned entity.”[^9]

Regulation 22(1) says:

> “Requesting entities and Authentication Service Agencies/OVSEs shall have their servers used for Aadhaar authentication request formation and routing to CIDR/Offline Verification respectively, to be located within data centres or cloud storage centres located in India.”[^9]

### Incidents and subcontractors

Regulation 14A requires notice to UIDAI no later than 72 hours after learning of misuse or compromise, cooperation with investigations, notification to affected holders, and responsibility for outsourced operations. The exact incident clause says the OVSE:

> “shall inform the Authority, without undue delay and in no case beyond 72 hours after having knowledge of misuse of any information or systems related to the Aadhaar framework or any compromise of Aadhaar related information.”[^9]

No entity may perform offline verification on behalf of another entity or person.[^9]

### Penalties

Aadhaar Act section 33A(1) states:

> “Where an entity in the Aadhaar ecosystem fails to comply with the provision of this Act, the rules or regulations made there under or directions issued by the Authority under section 23A, or fails to furnish any information, document, or return of report required by the Authority, such entity shall be liable to a civil penalty which may extend to one crore rupees for each contravention and in case of a continuing failure, with additional penalty which may extend to ten lakh rupees for every day during which the failure continues after the first contravention.”[^10]

Section 40 states:

> “Whoever,— … (b) being an offline verification-seeking entity, uses the identity information of an individual in contravention of sub-section (2) of section 8A, shall be punishable with imprisonment which may extend to three years or with a fine which may extend to ten thousand rupees or, in the case of a company, with a fine which may extend to one lakh rupees or with both.”

Regulation 25(1A) additionally authorises UIDAI action/penalty for process, obligation, lawful-purpose, information-supply, or audit-cooperation failures, after an opportunity to be heard; registration may also be terminated.[^9]

## Secure QR and tooling

UIDAI states that the Secure QR contains:

> “Ref ID; Name; Gender; DOB; Mobile; Email; Address; Photograph; 2048 bit digital signature”.

UIDAI’s annual report describes the QR more precisely as digitally signed name, address, photo, gender, DOB, masked registered mobile number, registered email address and a reference ID containing the last four Aadhaar digits and timestamp; it says this Secure QR is available on e-Aadhaar, Aadhaar letter, Aadhaar PVC card and mAadhaar.[^11]

The PVC circular states:

> “Similar to other forms of Aadhaar, it has a digitally signed secure QR code with photograph and demographic details”.[^5]

Therefore, e-Aadhaar and PVC carry the same **category/schema of Secure QR signed data**. Whether their byte-for-byte QR payload is identical for the same person and issue time is **not stated**.

### Official verifier/spec

UIDAI provides official verification applications, including a downloadable Windows “QR Code/Offline XML Reader” and Android/iOS scanner apps. Its page says the application displays demographics and photograph after signature verification and otherwise reports that the QR is not verified.

- Reader page: <https://uidai.gov.in/en/qr-code-reader>
- Windows installer linked there: <https://uidai.gov.in/images/authDoc/QrCodeReaderV4.2.msi>
- Signing certificates: <https://uidai.gov.in/en/data-and-download>

An official, current, platform-neutral **software library/SDK source package** for embedding Secure QR verification in a private application is **not stated** on the current English reader page. An official Secure QR specification link was visible on an older UIDAI-language page, but the current English page no longer exposes that link; the present primary source clearly provides the binary reader/apps and signing certificates, not a supported embeddable library.[^12]

## PAN-name verification

### Free Income Tax check

The official Income Tax instructions say:

> “Enter the PAN, Full Name, Date of Birth and Mobile number and click on ‘Continue’.”

> “Enter OTP and click on ‘Validate’ button.”[^6]

The official FAQ explains the purpose:

> “Check if the details of your PAN, such as name on the PAN card, date of birth are same as the details available in the PAN database.”[^7]

Any accessible valid mobile can receive the OTP, and one mobile number can verify at most five different PANs per day. The FAQ also says:

> “Yes, Verify PAN service is available for all registered users including external agencies. Bulk PAN / TAN verification is a separate service for external agencies that requires the approval of the department.”[^7]

This is therefore an official free way for a third party to test a **claimed name + DOB against a PAN**, subject to OTP and daily limits. It is not a PAN-to-name disclosure/search service, not bulk verification, and no free official API for general third-party name verification is stated.

Direct service URL: <https://eportal.incometax.gov.in/iec/foservices/#/pre-login/verifyYourPAN>

### Protean/NSDL

Protean’s official service is not free access: annual registration is ₹12,000 plus GST, registration is subject to Income Tax Department approval, and its API/file modes can incur usage charges. The output is matching status for submitted name and DOB rather than a general unrestricted disclosure of the PAN holder’s details.

Protean’s published eligible-entity list includes regulated financial entities, government entities, specified educational institutions, companies/government deductors meeting stated conditions, and entities required to file AIR/SFT. **“Sole proprietor” or “proprietorship” is not listed.**

Consequently:

- An ordinary sole proprietorship is **not stated as eligible** merely because it is a proprietorship.
- A sole proprietor might qualify only if the underlying business independently fits a listed category such as “Any other entity required to furnish … SFT”; whether Protean/ITD accepts that legal form is **not stated**.
- Protean asks for an incorporation certificate in its FAQ and the approval remains discretionary with ITD, which reinforces that eligibility cannot be assumed.

## Practical reading

For a private-business implementation using **Paperless Offline e-KYC XML**, register and obtain UIDAI approval before production verification. A sole proprietorship may apply because UIDAI’s own current form expressly permits that category.[^3][^1]

For **Secure QR-only** verification, the registration trigger is textually ambiguous after the 2025 amendment: QR verification remains regulated offline verification performed by an OVSE, but regulation 13A’s mandatory application sentence does not mention QR. Because UIDAI now maintains a general OVSE onboarding process, obtain written UIDAI confirmation or register rather than relying on the older “no license” FAQ.[^2][^1]

For PAN, the free Income Tax tool works for low-volume, interactive verification where the business already has the customer’s PAN, asserted full name and DOB; there is no primary-source support for a free bulk/API equivalent. Protean is the official scaled option in the researched sources, but an ordinary sole proprietorship is not on its stated eligibility list.[^7]

---

## References

1. [भारतीय जिजिष्ट पहचान प्राजधकरण अजधसूचना नई दिल्ली, 9 ...](https://uidai.gov.in/images/Gazette_dated_9_dec_2025.pdf)

2. [Offline Verification Seeking Entity - Unique Identification ...](https://uidai.gov.in/en/2-uncategorised/19593-offline-verification-seeking-entity.html) - UIDAI is mandated to issue an easily verifiable 12 digit random number as Unique Identity - Aadhaar ...

3. [[PDF] Application form for Offline Verification Seeking Entity (OVSE) - uidai](https://uidai.gov.in/images/ApplicationFormandTC.pdf)

4. [Secure QR Code Reader (beta) - Unique Identification Authority of India | Government of India](https://uidai.gov.in/en/306-faqs/authentication/secure-qr-code-reader-beta.html) - UIDAI is mandated to issue an easily verifiable 12 digit random number as Unique Identity - Aadhaar ...

5. [2. Aadhaar card can be ordered online by visiting ...](https://uidai.gov.in/images/Circular_dated_30_09_2020_regarding_Aadhaar_PVC_Card.pdf) - Similar to other forms of Aadhaar, it has a digitally signed secure QR code with photograph and demo...

6. [PAN Verification Online | Verify PAN Details - Income Tax](https://www.incometaxindia.gov.in/pan-verification) - Enter the PAN, Full Name, Date of Birth and Mobile number and click on 'Continue'. Enter OTP and cli...

7. [Verify Your PAN FAQ](http://www.incometax.gov.in/iec/foportal/help/e-filing-verify-pan-faq?mobile-app=1) - You can verify your PAN to: Check if the details of your PAN, such as name on the PAN card, date of ...

8. [Gazetted Notifications](https://uidai.gov.in/en/gazetted-notifications) - Uploaded On: 12-05-2026. Download. Download. Aadhaar (Authentication and Offline Verification) Amend...

9. [[PDF] सी.जी.-डी.एल.-अ. - uidai](https://uidai.gov.in/images/AADHAAR_AUTHENTICATION_AND_OFFLINE_VERIFICATION_REGULATIONS_2021.pdf)

10. [Aadhaar_Act_2016_as_amended.pdf](https://uidai.gov.in/images/Aadhaar_Act_2016_as_amended.pdf) - The identity information, other than core biometric information, collected or created under this Act...

11. [annual report - 2022-23](https://uidai.gov.in/images/UIDAI_Annual_Report-2022-23_English.pdf) - Aadhaar secure QR code is a quick response code provided by UIDAI for offline verification of identi...

12. [Secure QR Code Reader](https://uidai.gov.in/te/ecosystem-te/authentication-devices-documents-te/qr-code-reader-te.html)

