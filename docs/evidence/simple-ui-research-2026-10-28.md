# Simple UI for non-technical owners: research for the Training tab

Read 28 Oct 2026, for the Training tab rebuild (founder: "more buttons and short sentences").
Each finding is what the source says, its URL, and what it means for this screen. Evidence
class: every row is VENDOR-PUBLISHED or research read at the URL on 28 Oct 2026. Rows marked
SECONDARY quote a third party about the app, not the app maker.

| # | Finding | Source | What it means here |
|---|---------|--------|--------------------|
| 1 | Lower-literacy users read word by word, do not scan, skip dense text and settle for the first reasonable option. Rewriting raised their task success from 46% to 82%, and higher-literacy users improved too (68% to 93%). | https://www.nngroup.com/articles/writing-for-lower-literacy-users/ | Every line we show by default is read in full, so each one costs. Cut sentences; the gain is for every reader, not only the low-literacy one. |
| 2 | Same article: put the main point at the top, use one main column, avoid motion and fly-outs; aim near a 6th-grade reading level on key pages. | https://www.nngroup.com/articles/writing-for-lower-literacy-users/ | The verdict ("2 of 5 OK") goes first; one column of cards; no animated reveal of explanations. |
| 3 | 79% of test users scanned a new page; 16% read word by word. Concise text scored 58% better, a scannable layout 47% better, both with objective words 124% better. | https://www.nngroup.com/articles/how-users-read-on-the-web/ | Scanners need a number and a chip, not a sentence. Short, scannable and factual together beat any one of them. |
| 4 | Easy, short text is understood as well on a phone as on a computer; difficult text slows phone readers (about 30 ms more per word). NN/g's advice: keep mobile content brief and cut what is not needed. | https://www.nngroup.com/articles/mobile-content/ | Our owners are on phones. Brevity is what keeps comprehension equal on a phone, so the long judge reasons go behind "Why?". |
| 5 | With an average sentence of 14 words readers understand over 90%; at 43 words, under 10%. 11 words reads as easy, 21 as fairly difficult, 25 as difficult. | https://insidegovuk.blog.gov.uk/2014/08/04/sentence-length-why-25-words-is-our-limit/ (the post notes it may be out of date) | Our cap is tighter than GOV.UK's 25 words: about 60 characters (roughly 10 words) per visible line, enforced by a test. |
| 6 | Progressive disclosure: "Initially, show users only a few of the most important options"; put the rest behind a clearly labelled control; keep to two levels. | https://www.nngroup.com/articles/progressive-disclosure/ | Default view: verdict, one primary button, problem cards. "Why?", "See the chat" and "How this works" hold the rest, one level down, each labelled for what it opens. |
| 7 | Minimum touch target 1 cm x 1 cm; primary calls to action deserve a larger target; space targets apart to avoid slips. | https://www.nngroup.com/articles/touch-target-size/ | 44px minimum on touch for every button; the verdict's primary button is full width on a phone. |
| 8 | Google Design on emerging markets (India named): minimise text, avoid hierarchies understood only through language, use icons to identify components and features, and test with low-literacy users. | https://design.google/library/connectivity-culture-and-credit | The verdict carries an icon as well as words; status uses a coloured dot plus one word, so meaning survives a skipped word. |
| 9 | Meesho (Indian commerce app for first-time online users) says its app is "much simpler, less cluttered" and relies on "visual iconography and visual cues" because many users would rather not read dense copy; it kept vertical-only scrolling like the social apps users learned on. SECONDARY (CleverTap interview). | https://clevertap.com/blog/how-meesho-achieves-dynamic-ecommerce-growth-part-2-simplicity-and-personalization/ | One vertical list of cards, no side-by-side panels or horizontal strips to learn. |
| 10 | Google Business Profile, an app Indian SMB owners use, shows performance as named metrics with counts ("Calls", "Directions", "Views"), only those that apply. | https://support.google.com/business/answer/9918094?hl=en-GB | A status is a short name and a number. "2 of 5 OK" rather than "Right every time on 2 of your 5 tests". |
| 11 | Khatabook (ledger for Indian shop owners) relaunched in 2018 "to make it as simple for the users as possible", building on the familiar paper khata rather than accounting terms. SECONDARY (Substack analysis). | https://ameya.substack.com/p/how-khatabook-became-the-premier | Use the owner's words, not ours: no "script version", "tries", "judged", "reliable". |

## What we did not verify

- Vyapar, OkCredit, PhonePe and Paytm for Business: no design write-up from the companies was
  found; the search returned funding and press pieces only. Nothing here is claimed about them.
- Meesho's own design blog post on first-time users returned HTTP 403 and was not read.
- The Google I/O Next Billion Users talks were found only as third-party summaries; not cited.
- That "OK" is the plainest status word for this audience is a choice made from findings 3,
  10 and 11 (short, common, objective). It has not been tested with Calevate's owners.
