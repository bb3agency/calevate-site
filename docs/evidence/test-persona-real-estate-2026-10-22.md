# Test persona: a real-estate developer in Vijayawada

22 Oct 2026. A **fictional** business for testing the real-estate niche end to end: account
setup, two agents, knowledge, practice tests and test calls. Every name, project, price and
address below is invented. Never publish any of it, and never use it with real customers.
Prices are plausible test figures, not market data.

---

## 1. The owner

| | |
|---|---|
| Name | **Ramana Kovuri** (he/him), 46 |
| Role | Founder and managing partner |
| Home town | Vijayawada, Andhra Pradesh |
| Background | Civil engineer. Site engineer for 12 years, then started his own firm in 2015. |
| Languages | Telugu first. Speaks Tenglish at work ("site visit", "booking amount", "possession"). Reads English, prefers Telugu on the phone. Some Hindi for labour contractors. |
| Tech | Lives on WhatsApp. Uses a laptop only for Excel and email. No CRM: leads sit in a spreadsheet and a notebook. |
| Team | 1 sales manager (**Sravani**), 2 site executives, 1 accountant. |

**His problem:**
- He pays for Facebook and property-portal ads, and the leads arrive at all hours.
- His sales manager calls them back the next day, by which time half have already spoken
  to another builder.
- Calls to the office after 7 pm and on Sundays go unanswered, and Sunday is when families
  want to visit sites.
- NRI buyers call from the US and the Gulf at odd hours.

**What he wants:**
- Every enquiry answered and qualified in minutes, day or night.
- A site visit booked.
- The hot leads on Sravani's phone the same day.

**What he fears:**
- An agent quoting the wrong price, or promising a flat that is already sold.
- An agent sounding like a call centre, or sounding robotic to elders.
- Annoying people who only filled in a form.

**How he judges it:** "Did it get the BHK, the budget and a site-visit date, and would my
father understand it?"

## 2. The business

**Vennela Nest Developers**, partnership firm, Vijayawada. Office: "Vennela Nest Developers,
first floor, Benz Circle, Vijayawada" (fictional address).

| Project | What it is | Where | Status |
|---|---|---|---|
| **Vennela Residency** | Gated apartments, 2 towers, 9 floors, 144 flats | Poranki, Vijayawada | Under construction; possession promised **December 2027** |
| **Vennela Meadows** | Open plots in a gated layout | Near Gannavaram | Plots ready for registration |

### Vennela Residency

| Type | Size | Starting price (test figure) |
|---|---|---|
| 2 BHK | 1,150 sq ft | ₹5,400 per sq ft, about **₹62 lakh** |
| 3 BHK | 1,580 sq ft | ₹5,400 per sq ft, about **₹85 lakh** |

- Extra charges: car parking ₹2.5 lakh; club house and corpus ₹1.5 lakh. GST and
  registration are extra, as per government rules.
- Booking amount: ₹2 lakh, refundable within 15 days.
- Amenities: swimming pool, gym, children's play area, 24-hour security, power backup,
  rainwater harvesting.
- Facing: both east and west facing flats in each tower. Vastu-compliant layouts.
- Home loans: "most major banks have approved the project" (no bank named, so the agent
  never names one).

### Vennela Meadows

- Plot sizes 150 to 300 square yards, **₹18,000 per square yard** (test figure).
- Approvals: layout approved; documents shown at the site office.

### Site visits

- Every day, 10 am to 6 pm, at the site office of each project.
- Free pickup within Vijayawada on Saturdays and Sundays, booked one day ahead.

### What only a person decides

- The final price, discounts and availability of a particular flat number or floor.
- Payment plans.
- Anything legal: documents, approvals, title.

## 3. Who calls, and what they ask

| Caller | Language | Typical questions |
|---|---|---|
| Young IT couple from Hyderabad, buying near family | Tenglish | "2 BHK price ఎంత?", "possession ఎప్పుడు?", "loan వస్తుందా?" |
| Retired government employee, buying a plot | Pure Telugu, slow | "plot rate ఎంత?", "documents అన్నీ clear గా ఉన్నాయా?" |
| NRI in Dallas or Dubai, buying for parents | English, sometimes Telugu | "Is it RERA registered?", "Can I book online?", "video call site visit?" |
| Labourer or broker | Hindi or Telugu | "commission ఇస్తారా?", "which floors are left?" |
| Facebook ad lead, called back by the agent | Unsure, busy | "ఎవరు మాట్లాడుతున్నారు?", "నేను form fill చేశానా?" |

Objections to prepare for:
- "The price is too high; the builder next door is cheaper."
- "What if possession gets delayed?"
- "Is it Vastu?"
- "Any discount if I book today?"
- "Are there hidden charges?"
- "Is this flat still available?"
- "Are you a robot?"

## 4. The two agents to create

### Agent 1: inbound, "Property enquiries" (real-estate starter, inbound)

- **Job:** answer every call, find out what the caller wants, collect the details, and book
  a site visit.
- **Details to collect** (from the starter's capture fields):
  - the area they want;
  - BHK, or plot size;
  - budget;
  - when they plan to buy;
  - whether they need a home loan;
  - name, and a site-visit day.
- **Must never:**
  - quote a final price, a discount or a particular flat's availability (offer a site
    visit instead, or say Sravani will call);
  - give legal advice.
- **Hand-over:** to Sravani in office hours (her number is the founder's own test number).
- **Opening line** (under 120 characters, ends with "?"):
  > నమస్కారం అండి, Vennela Nest Developers. చెప్పండి, ఏ project గురించి అడుగుతున్నారు?

### Agent 2: outbound, "Buyer follow-up" (real-estate starter, outbound)

- **Job:** call back an ad lead who filled in a form, confirm they are interested, qualify
  them, and book a site visit.
- **Only for people who filled in a form.** No cold lists.
- **Opening line** (the permission opener, under 120 characters):
  > హలో అండి, నేను Vennela Nest Developers నుండి call చేస్తున్నాను. ఒక రెండు నిమిషాలు మాట్లాడొచ్చా?
- **Flow:**
  - Busy: book a call back.
  - Not interested: thank them and close, once.
  - Yes: "మీరు Poranki flats గురించి enquiry చేశారు కదా", then qualify and book.

## 5. Knowledge to add (pinned facts, ready to paste)

Each item is named the way callers say it, in both scripts. This avoids the mix-up where a
Raghava agent read the chilli-powder price for ఎండు మిర్చి.

1. Vennela Residency (Poranki, Vijayawada): 2 BHK 1150 square feet, starting around sixty two lakhs. 3 BHK 1580 square feet, starting around eighty five lakhs. Final price only from our sales team.
2. Vennela Residency extra charges: car parking two and a half lakhs, club house and corpus one and a half lakhs. GST and registration extra as per government rules.
3. Vennela Residency possession: December 2027. Under construction now.
4. Booking amount: two lakhs, refundable within fifteen days.
5. Vennela Meadows plots (near Gannavaram): 150 to 300 square yards, eighteen thousand rupees per square yard.
6. Site visits: every day, ten am to six pm. Free pickup within Vijayawada on Saturday and Sunday, book one day ahead.
7. Amenities at Vennela Residency: swimming pool, gym, children's play area, twenty four hour security, power backup.
8. Both east facing and west facing flats are there. All layouts are Vastu compliant.
9. Home loans: most major banks have approved the project. Our team helps with the loan papers.
10. Which flat or floor is available, discounts and payment plans: only Sravani from our sales team can confirm. Offer a site visit or a call from her.

## 6. Test plan

**Practice tests:** run them after both agents are published, and note the first score
before any change.

**Test calls** (from the founder's own phone):

| # | Agent | Caller plays | A good result |
|---|---|---|---|
| 1 | Inbound | IT couple, Tenglish: 2 BHK price, possession, loan | Gives the "starting around" price with "final price from sales team"; collects BHK, budget and timeline; books a site visit with a day |
| 2 | Inbound | Retired man, slow Telugu: plot rate, documents | Plot rate per square yard; on documents says the team shows them at the site; never gives legal advice |
| 3 | Inbound | NRI in English: RERA, video call, discount | Stays in English; "discount only from Sravani"; never invents a RERA number; offers a call from Sravani |
| 4 | Inbound | "Is the 5th floor east-facing flat available? Book it now." | Never confirms availability or a booking; offers Sravani or a site visit |
| 5 | Outbound | Busy: "ఇప్పుడు drive చేస్తున్నా" | Short permission opener heard in full; asks a time; books a call back; ends |
| 6 | Outbound | "నేను form ఏం fill చేయలేదు" | Apologises, offers to remove the number, does not pitch |
| 7 | Either | "మీరు AI ఆ?" midway | Answers truthfully and carries on |

**Score each call out of 10, as you did for Raghava**, on:
- the opening heard;
- prices right;
- no promises it cannot keep;
- details captured;
- how natural it sounded.

## 7. Creating the account

- **Business name:** Vennela Nest Developers. **Type:** real estate. **City:** Vijayawada.
- **Phone numbers:** use only your own test number for the owner, Sravani and every test
  call.
- **GST, PAN, RERA:** leave them empty, or use the test placeholders our sign-up allows.
  Never type an invented ID that looks real.
- **Outbound:** outbound needs a verified KYC record and the no-cold-calls pledge (D-692).
  For test calls to your own number, use the agent's test-call button. Campaigns stay off
  until KYC is real.
