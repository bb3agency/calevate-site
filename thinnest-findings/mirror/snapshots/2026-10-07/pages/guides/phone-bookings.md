> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Take bookings over the phone

> A clinic line that answers, gathers four details and reads them back — built in about twenty minutes.

The most common thing a small business does on the phone is take a booking. It
is also the thing most likely to go wrong: a name misheard, a day assumed, an
appointment made with a doctor who does not work Mondays.

This guide builds a clinic line that gets it right. The same shape works for a
salon, a garage, a dentist or a viewing appointment — change the names and the
hours.

## What you are building

A caller rings, is asked for four things one at a time, and hears the whole
booking read back before it is confirmed.

<Steps>
  <Step title="Write down what is actually true">
    Before touching the agent, write your real availability. Not "we're open
    weekdays" — the actual person, the actual days, the actual hours.

    This is the part people skip, and it is the part that decides whether the
    agent invents things.
  </Step>

  <Step title="Put it in the agent's instructions">
    On the agent's **Behaviour** page, replace the instructions with something
    shaped like this:

    ```text theme={null}
    You book appointments for the clinic, on the telephone.

    WHAT YOU NEED, and you may not book without all four:
      1. the patient's name
      2. which doctor or which problem they are calling about
      3. the day
      4. the time

    ASK FOR ONE THING AT A TIME. This is a phone call, not a form. A caller
    who is asked three questions in one breath answers the last one and
    forgets the rest.

    READ BACK the whole appointment before you confirm it — name, doctor,
    day, time — and wait for them to agree. Getting a booking wrong is worse
    than taking another twenty seconds.

    WHEN THEY PAUSE, LET THEM FINISH. People hesitate when they are looking
    at a calendar. Silence is them thinking, not them finishing.

    WHAT IS AVAILABLE THIS WEEK. Offer these in words; the caller cannot see
    a screen, so never say "as shown" or "tap".
      Doctor Sharma (general physician) — Monday to Friday, 10am to 1pm
      Doctor Iyer (dentist)             — Tuesday and Thursday, 3pm to 7pm
      Doctor Kapoor (physiotherapy)     — Monday, Wednesday, Friday, 4pm to 8pm
      Saturday                          — emergencies only
      Sunday                            — closed

    If the time they want is taken or outside these hours, say so plainly and
    offer the nearest two that are free.

    NEVER invent a doctor, a speciality or an hour that is not written above.
    If you are asked something you do not know — a price, a test result,
    whether insurance is accepted — say you do not know and offer to have the
    desk call them back.
    ```

    <Tip>
      Note "Doctor Sharma", not "Dr. Sharma". A full stop inside a name ends a
      sentence early when it is spoken, and the caller hears the agent stop
      halfway through the name.
    </Tip>
  </Step>

  <Step title="Check it can take contact details">
    On the **Actions** page, confirm lead capture and escalation are on. They
    are on for a new agent — this is a look, not a task. A booking line needs to
    take a phone number, and needs a way to hand over when it cannot help.

    Knowledge search on calls is on too, so the agent answers "do you take my
    insurance?" from your own documents rather than guessing.
  </Step>

  <Step title="Set the greeting">
    On the **Voice** page, set **First words** to how you would answer the
    phone:

    ```text theme={null}
    Sunrise Clinic, how can I help you?
    ```

    Short, and it names the business. A caller who dialled a clinic wants to
    know they reached the clinic.
  </Step>

  <Step title="Call it and book something">
    Ring your number and go through a real booking.
  </Step>
</Steps>

## What a good call sounds like

This is a real transcript from a line set up exactly as above.

<CodeGroup>
  ```text Booking theme={null}
  Caller:  I want to book an appointment
  Agent:   Sure! May I have your name, please?

  Caller:  Ashutosh
  Agent:   Thank you, Ashutosh. Which doctor would you like to see, or what
           health concern would you like to discuss?

  Caller:  I need to see the dentist
  Agent:   Great. Which day would work best for you — Tuesday or Thursday?

  Caller:  Thursday
  Agent:   And what time on Thursday would you prefer between three p.m. and
           seven p.m.?

  Caller:  Four p.m.
  Agent:   You'd like to see Doctor Iyer on Thursday at four p.m. Is that
           correct?
  ```
</CodeGroup>

Four things went right there, and each one was asked for in the instructions:

* **One question per turn.** The caller never had to hold two answers in their head.
* **It only offered real days.** Tuesday or Thursday, because that is when the dentist works.
* **It constrained the time** to the hours that exist, without being asked again.
* **It read the whole thing back** before confirming.

## Test that it will not make things up

Setting it up is the easy half. Before you put the number anywhere, ring it and
try to make it lie.

<AccordionGroup>
  <Accordion title="Ask for someone who does not work there">
    *"Can I book with Doctor Mehta please?"*

    You want a refusal — a name that is not on your list should be met with "we
    do not have a Doctor Mehta" and an offer of who you do have.

    The failure to watch for is an agent that says **"Sure, which day?"** and
    only mentions the problem afterwards. On a phone the caller has already
    started answering.
  </Accordion>

  <Accordion title="Ask for a service you do not offer">
    *"Do you have a cardiologist?"*

    Same shape. "We do not have a cardiologist" — not a booking.
  </Accordion>

  <Accordion title="Ask for a real person on a day they do not work">
    *"Can I see the dentist on Monday morning?"*

    A good answer names the real days: "the dentist is here Tuesday and
    Thursday, three to seven".

    Watch for **"Yes, you can see the dentist on Monday morning"** followed by a
    correction. Read on a page you would catch it. Heard on a phone, the caller
    stopped listening after "yes".
  </Accordion>

  <Accordion title="Ask something only your office knows">
    *"How much does a filling cost?"* or *"Do you take Star Health insurance?"*

    You want "I do not have that" plus an offer to have someone call back. A
    made-up price is the single most expensive thing a phone agent can do.
  </Accordion>

  <Accordion title="Ask about a day you are closed">
    *"Are you open on Sunday?"*

    Straightforward, and worth checking anyway — it is the question most likely
    to be answered from general knowledge about clinics rather than from your
    instructions.
  </Accordion>
</AccordionGroup>

<Tip>
  Run each of these on a **fresh call**, not one after another in the same
  conversation. An agent that already knows you wanted the dentist will answer
  differently from one hearing you for the first time, and it is the first time
  that matters.
</Tip>

## When it gets one wrong

Almost always the fix is in your instructions, not in the settings.

| What happened | What to add |
| - | - |
| Invented a person or a service | "NEVER invent a doctor, a speciality or an hour that is not written above" |
| Asked three things at once | "ASK FOR ONE THING AT A TIME" |
| Confirmed a booking without a name | List what you need and say it may not book without all of it |
| Guessed a price | Name the things it does not know — prices, results, insurance — and what to do instead |
| Cut people off mid-sentence | "WHEN THEY PAUSE, LET THEM FINISH" |

Be specific and be blunt. "Be helpful and accurate" changes nothing. "Never
offer a time that is not written above" changes a lot.

## Before you print the number anywhere

<Warning>
  Ring it yourself and try the **hardest** question you actually get — not the
  easy one. The awkward one, the one with a condition attached, the one where
  the honest answer is "it depends". If it handles that, it will handle the
  hours question.
</Warning>

Then hand the number to somebody who has never seen the instructions and ask
them to book something. They will phrase things you did not think of, which is
the entire point.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.