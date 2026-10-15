> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Turn a calling list into a filled spreadsheet

> Ring a list of leads and get their answers back in the rows you started with, with a line about each call.

You have a list of people to ring and a set of things to find out about each one.
By the end of this your agent rings them, asks, and writes the answers into the
row that person already occupies — plus a sentence or two about how the call
went, including for the ones who hang up on you.

This is the setup a recruitment, admissions or lead-qualification team ends up
with. It takes about twenty minutes.

<Note>
  You need a [spreadsheet connected](/agent/spreadsheet) and a
  [phone number](/channels/phone-numbers). If you have neither yet, do those
  first — this guide assumes both.
</Note>

## Start from the sheet, not the agent

The order matters. Your columns decide what the agent can record, so a column
you add later is one it has been asked nothing about.

<Steps>
  <Step title="Put your leads in, one row each">
    Import your list into Grist with whatever you already know — name, mobile,
    district. These rows are the ones the calls will fill in, so the numbers
    must be the ones you are going to dial.

    ```
    CANDIDATE_NAME    MOBILE_NO     DISTRICT
    Ambarish Sadhu    9775778000    Bardhaman
    Arpita Sengupta   7063513131    Bardhaman
    ```
  </Step>

  <Step title="Add a column for every answer you want">
    One column per question. Keep the names plain — the agent reads them, so
    `AGE` and `QUALIFICATION` work and `col_7` does not.

    Give each a short **description** in Grist ("the candidate's current
    district"). That description is the clearest instruction you can give about
    what belongs in a column, and it costs you nothing.

    <Tip>
      For a question with fixed answers, make it a **Choice** column and list
      them. The agent is then held to your own words, so you get `Interested`
      every time instead of `interested`, `yes interested` and `keen`.
    </Tip>
  </Step>

  <Step title="Add a Summary column">
    Call it **Summary**. It is the one that gets filled when nothing else can —
    the person who says only *"not now, I'm busy"* has answered none of your
    questions and still told you something worth keeping.
  </Step>

  <Step title="Pin the table">
    **Actions → Spreadsheet → Grist**, paste your key, choose the document and
    the table.

    <Warning>
      **Do this again whenever you add a column.** The column list is cached
      when you pin, so a column added afterwards is invisible until you pick
      the table again. This is the single most common way this setup goes
      quietly wrong.
    </Warning>
  </Step>
</Steps>

## Tell it which row belongs to whom

Without this, every call adds a new line and your imported rows stay empty.

<Steps>
  <Step title="Set the match column">
    On the same card, under **Update an existing row**, choose `MOBILE_NO` and
    compare it as a **Phone number**.

    Digits are compared, last ten, so the sheet saying `9775778000` and your
    campaign dialling `+919775778000` are the same person. They rarely match as
    text, which is why comparing as text is the wrong choice here.
  </Step>

  <Step title="Fill in what the call already knows">
    Under **Fill from campaign variables**:

    ```
    MOBILE_NO=phone
    CANDIDATE_NAME=name
    ```

    The left side is your column, the right side is the variable your campaign
    supplies. Your agent is told not to read someone's own number back to them,
    so without this the number never arrives — it is known, but nobody says it
    out loud.
  </Step>
</Steps>

## Choose when it writes

On the spreadsheet card, set **When to save** to **After the call**.

For a questionnaire this is almost always right. The whole conversation is read
at once, so an answer given early lands in the right column, somebody who
corrects themselves is recorded once, and the caller never waits while a row is
written.

Leave it on **During the call** only if you are watching the sheet live and want
to see rows appear as the words are spoken.

## Turn on summaries

**Voice → Summarise each call.**

Two or three sentences per call, on the call in **Usage → Calls** beside the
transcript, and in the `Summary` column you made.

<Note>
  The switch is what starts it — the column on its own does nothing. This is
  deliberate: a column should never quietly begin costing you anything.
</Note>

## Ring the list

**Voice Campaigns → New voice campaign.** Upload the same list as a CSV and map
its columns:

* **Phone number** → the column with the mobile in it
* `{{lead_name}}`, `{{mobile_no}}` → the matching columns

The names on the right of your **Fill from campaign variables** box must be the
variables this campaign actually supplies. Map `MOBILE_NO=mobile_no` here and
send `phone` there and the column stays empty — nothing errors, it simply never
fills.

## Check the first call before you run the rest

Ring one person. Yourself, ideally. Then:

<Steps>
  <Step title="Open Usage → Calls">
    The call should read **Answered**, with a **Summary** tab beside the
    transcript.
  </Step>

  <Step title="Open your sheet">
    Their answers should be in **their existing row**, not a new one at the
    bottom.

    A new row at the bottom means the match did not happen. Check the number in
    the sheet is the number you dialled, and that **Update an existing row** is
    set to that column.
  </Step>

  <Step title="Then start the campaign properly">
    A list of five hundred writing into the wrong rows is five hundred rows to
    clean up by hand.
  </Step>
</Steps>

## What you end up with

Your original rows, filled in — one line per person rather than one per call,
whatever number of times you ring them. A summary against each call for the ones
worth reading about. And for the ones who said no, a record saying so, which is
what stops you ringing them again next month.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.