# Changelog

Each deploy shows its version, commit and build date in the sidebar footer and on the sign-in
page (`apps/web/package.json` holds the version). Dates are IST.

## 0.3.4 — 15-Nov-2026

- A long main task wraps and opens folded to six lines with **Show more** / **Show less**;
  long material notes fold to three.

## 0.3.3 — 15-Nov-2026

- A page opened while a deploy swapped the server no longer shows "This screen stopped": a
  missing code file reloads the page once onto the new build.

## 0.3.2 — 15-Nov-2026

- **Let Pip, our AI agent, generate the script:** a band with a **Generate** button between
  Materials and Script, on the new campaign page and the campaign page. Pip writes the script
  from the main task and materials; it appears below for review.

## 0.3.1 — 15-Nov-2026

- **New campaign is one page**, a complete new design: 1 Main task (Save), 2 Materials (files,
  website and video links, notes), 3 Script (who speaks it, and Create and write the script with
  Pip). The Calls & recordings, Questions to answer and Improve tabs are there from the start,
  empty until the campaign calls. The four-step wizard, its why / goal / name fields and the
  step strip are gone; the name is made from the main task.
- The campaign page's main task shows as text with **Edit**; editing gives **Save** and **Cancel**.

## 0.3.0 — 15-Nov-2026

- **Hear it first:** ring your own phone with the campaign's script before Start.
- **Test a second opening:** half the people hear it, half the script's own; goals reached are
  compared per opening. The AI and recording notices are always said with it.
- **Improve tab** on a running campaign: best hours to call (IST answer rates), the opening test,
  a draft for the people never reached, and a WhatsApp follow-up from the Follow-ups page.
- Results card adds call backs booked and opt-outs.

## 0.2.0 — 15-Nov-2026

- **Campaigns own their script (D-992).** A new campaign starts with its main task. The
  campaign page then collects materials (files, links, notes), Pip writes the script from both,
  and Start puts only that script on the chosen agent, which is the voice.
- Campaign pages gain **Calls & recordings** and **Questions to answer** tabs; an answer is kept
  as a note learned from the calls, and the next script works it in.
- Suggestion review: **Review** opens a row on a tinted ground with **Update** and **Cancel**;
  once updated, only the final wording shows and the button reads **Edit**.
- **Always the latest version:** every page checks `/version.json` on load and reloads once
  to a newer deploy; an open page offers **Update now** when one lands, and never reloads over
  unsaved work.

## 0.1.0

- Everything before versioned releases.
