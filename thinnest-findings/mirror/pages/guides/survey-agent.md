> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Create a survey agent

> Ask the same questions of a thousand people and get answers you can count, not a thousand transcripts.

A survey is not a conversation you file away — it is a column you add up. The
difference between a good survey agent and a bad one is almost entirely whether
the answers come back in a form you can count.

This builds one that rings a list, asks a fixed set of questions, and leaves you
a sheet you can sort, filter and total.

<Note>
  Close relative of [Turn a calling list into a filled
  spreadsheet](/guides/calls-into-a-spreadsheet). That one fills rows you
  already have, for leads you already know. This one collects fresh answers from
  people you know nothing about yet, and cares about counting them.
</Note>

## Make the answers countable before you make the agent

The single decision that determines whether this works.

Asked "how satisfied were you", people say *very*, *quite good*, *ok ok*, *no
complaints*, *theek hai*. Every one of those is a true record and the column is
useless: you cannot sort it, filter it, or say what percentage were satisfied.

<Steps>
  <Step title="Make every answerable question a Choice column">
    In Grist, set the column type to **Choice** and list the answers you will
    accept.

    ```
    SATISFACTION   → Very satisfied / Satisfied / Neutral / Unhappy / Very unhappy
    WOULD_RECOMMEND → Yes / No / Unsure
    HEARD_ABOUT_US → Friend / Instagram / Google / Newspaper / Other
    ```

    The agent is then held to your own words. `theek hai` is recorded as
    `Neutral`, and an answer that fits none of them is not written at all
    rather than being rounded into one that would mislead you.
  </Step>

  <Step title="Leave open questions as Text, and expect few">
    One or two at most. *"Anything else you would like us to know?"* belongs in
    a Text column and is read by a person, not counted.

    A survey of eight open questions is eight columns nobody will ever read.
  </Step>

  <Step title="Describe each column in Grist">
    A one-line description on each column — "how satisfied they were with the
    delivery, not the product" — is the cheapest accuracy you can buy. It is
    read by whatever fills the column.
  </Step>

  <Step title="Add a Summary column">
    For the colour the choices cannot hold: who was in a hurry, who was angry,
    who asked a question you had not thought of. It is also the only thing that
    gets recorded when somebody refuses.
  </Step>
</Steps>

## Write the questions as a script

**Agent → Behaviour.** A survey prompt is unusual in that the ORDER is the
point — you want every respondent asked the same things the same way, or your
totals are comparing different questions.

```
You are calling on behalf of {{business}} to ask four quick questions.
Say it will take one minute. Ask them in this order, one at a time,
and wait for each answer:

1. How satisfied were you with your recent order?
   Very satisfied, satisfied, neutral, unhappy, or very unhappy?
2. Would you recommend us to a friend? Yes, no, or unsure.
3. How did you first hear about us?
4. Anything else you would like us to know?

Do not suggest an answer. Do not argue with an answer.
If they decline, thank them and end the call.
```

<Warning>
  **Do not let it improvise the options.** An agent that offers "so, good or
  bad?" has asked a different question from the one on your form, and you will
  never know which respondents got which.
</Warning>

<Tip>
  Ask the numbered questions first and the open one last. People hang up partway
  through, and you would rather lose the comment than the countable answers.
</Tip>

## Set it to write after the call

On the spreadsheet card, **When to save → After the call**.

For a survey this matters more than anywhere else. The whole conversation is
read at once, so an answer given out of order still lands in the right column,
and someone who says *"actually, make that satisfied"* is counted once. Saving
mid-call would also put a pause between each question, which on a
four-question survey is four pauses in ninety seconds.

## Record the refusals too

**Voice → Summarise each call.**

Most of your list will not answer your questions. On a survey that is not
failure — it is your response rate, and you need it to know what your results
are worth.

A call where somebody says only *"I'm busy, don't call again"* fills the Summary
column and nothing else. That row is doing real work: it tells you the call
happened, it tells you why there are no answers, and it tells you not to ring
them next time.

<Note>
  If you also make a column for the outcome — Choice, with
  `Completed / Refused / Busy / Wrong number` — it fills from what they said,
  and then your response rate is a filter rather than a count of blanks.
</Note>

## Ring the list

**Voice Campaigns → New voice campaign**, upload your CSV, map the phone column
and `{{lead_name}}`.

<Steps>
  <Step title="Ring twenty people first">
    Not five hundred. Twenty is enough to see whether a question is being
    misheard, and cheap enough to throw away.
  </Step>

  <Step title="Read those twenty in the sheet, not the transcripts">
    Sort by each Choice column. If one is mostly empty, that question is not
    landing — usually because the options were not read out, or the wording
    invites a sentence instead of a choice.
  </Step>

  <Step title="Fix the script, then run the rest">
    Changing the question after four hundred calls means four hundred answers
    to a different question.
  </Step>
</Steps>

## Reading the results

Everything countable is a column of your own words, so Grist does the rest —
group by `SATISFACTION`, count the rows, done. No parsing, no cleaning, no
reading.

The Summary column is for the twenty minutes afterwards when you want to know
*why* the unhappy ones were unhappy. That is the part a total cannot tell you,
and the part worth a person's time.

<Note>
  **Timing changes your answers more than wording does.** Nobody answers a
  survey at 9am on a Monday. Set the campaign's calling window to when your
  customers are free, or you are measuring who was available rather than who was
  satisfied.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.