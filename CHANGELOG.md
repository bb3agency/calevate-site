# Changelog

Each deploy shows its version, commit and build date in the sidebar footer and on the sign-in
page (`apps/web/package.json` holds the version). Dates are IST.

## 0.4.7 — 15-Nov-2026

- Step 4's sections fold. Each name sits on the edge of its card as a coloured tab: press it to
  fold the card to a thin bar and press again to open it. **Collapse all** and **Expand all**
  sit beside the step's heading. Voice & call settings (blue, folded at first, saying how many
  settings this campaign changes), Mandatory Regulatory Compliance Checks (amber), Add people
  (green), People to call (violet) and Other call settings (dark).

## 0.4.6 — 15-Nov-2026

- The compliance card asks **Where did this list come from?** directly, marked as mandatory
  under TRAI's Telecom Commercial Communications Customer Preference Regulations, 2018 and the
  Digital Personal Data Protection Act, 2023. The old checklist rows, "You can fix this" badges
  and the "Record where this list came from" heading are gone.
- Adding people is no longer a compliance check: **Add people** is its own always-open section
  (Excel, CSV, paste, one at a time, or from your leads), above **People to call**. Its button
  shows only once there is someone to add. "File tips" is gone; the file hint says other
  columns tell the agent about each person.

## 0.4.5 — 15-Nov-2026

- **Mandatory Regulatory Compliance Checks** is now a full-width card lined up with the
  Agent and test call card above it, with the launch summary inside it rather than nested in
  a second box.

## 0.4.4 — 15-Nov-2026

- **Pip's campaign script no longer gives up after one try.** When its script breaks a call
  rule, Pip now fixes it again (two rounds by default, set in the console as "Assistant: repairs
  on a campaign script") instead of handing it to the backup assistant, which could not fit a
  whole Telugu script and cut it off.
- When Pip cannot write the script, the Script section says why (a call rule it kept breaking,
  the AI not answering, Pip stopping, or the AI allowance being used up) and offers **Try
  again**. A used-up allowance links to the AI allowance page instead. Generate becomes Try again
  too, with no Dismiss needed first.
- While Pip writes, the Script section shows how long it has been and that it usually takes
  about a minute, beside Stop.

## 0.4.3 — 15-Nov-2026

- **People to call** takes an Excel sheet (.xlsx) as well as a CSV, pasted rows, or names and
  numbers typed one at a time. The sheet is read on the server and checked like a CSV.
- **Other call settings** replaces "Start later or repeat" and the "How it calls" summary: the
  hours it may call (IST, 9 am to 9 pm), an optional later start, and **If nobody answers**: try
  again at the same time the next day until they are reached, on up to 5 days.

## 0.4.2 — 15-Nov-2026

- **Pip's campaign script is checked like every Pip script.** Before you see it, the call-mistake
  checks read it and Pip rewrites what they find (three questions in one turn and the like), and
  an opening line that breaks the opening rules is written again. What Pip could not fix, or kept
  as you had it, is listed above the changes, and a script written by the backup assistant says so.
- A campaign's first script is written whole for your business from the main task and materials,
  starting from your trade's steps, instead of as a change to an empty script.
- Generate now checks your AI allowance first, and is not available while viewing as the client.
- Creating a campaign: if one material is refused, pressing again adds only the ones not yet added.

## 0.4.1 — 15-Nov-2026

- "Before you launch" is now **Mandatory Regulatory Compliance Checks**: foldable, open by
  default, with "N checks to answer" or "All checks done" on its folded line. Launch stays
  disabled until every check is answered, and the server's compliance gate refuses it anyway.

## 0.4.0 — 15-Nov-2026

- **Agents hold default settings; campaigns override them (D-994).** Step 4 gains **Voice & call
  settings**: the agent's own value for language, speaking speed, longest call, silence
  handling, re-ask wait, background sound and filler lines, and a box per setting for this
  campaign's own. Start and Test call put them on the agent with the script; a save while the
  campaign holds the agent applies at once. The agent's stored defaults never change.
- The agent's Script tab says which campaign's script it is carrying, with a link to edit it there.

## 0.3.7 — 15-Nov-2026

- Step 4 is now **Agent and test call**: the list of your agents to choose from (while the campaign
  is a draft), then **Test call**, where the chosen agent rings your phone speaking this campaign's
  script. The second-opening test left this step; what a call says belongs in the script.

## 0.3.6 — 15-Nov-2026

- A campaign file that is already in your knowledge is no longer refused as a duplicate: the
  existing copy is attached to the campaign and used.

## 0.3.5 — 15-Nov-2026

- Uploading a material: a dashed box saying **Click to choose a file, or drag it here** replaces
  the browser's plain file field, and shows the chosen file's name and size.

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
