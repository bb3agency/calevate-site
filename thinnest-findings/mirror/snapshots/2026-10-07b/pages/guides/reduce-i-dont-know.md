> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Cut the "I don't know" answers

> A weekly loop using the gaps report — the highest-return half hour in the product.

Your agent will say it does not know rather than inventing an answer. That is
the behaviour worth having, and it also hands you a list of exactly what to fix.

Most teams never open it.

## The loop

<Steps>
  <Step title="Open the gaps report">
    **Analytics → Questions it could not answer.**

    Every row is a question a real customer asked, which the agent searched your
    material for and found nothing on. Sorted by how often it was asked.
  </Step>

  <Step title="Sort the list into three piles">
    | Pile | Example | Do |
    | - | - | - |
    | **The answer exists, but not in the agent's material** | "Do you ship to Nepal?" — it is in an email template somewhere | Paste it into Knowledge as text |
    | **The answer exists nowhere** | "What's your GST number?" | Write it down once, then paste it |
    | **Not answerable from documents** | "Where is my order #10432?" | Needs an [action](/guides/order-status), not knowledge |

    That third pile is the valuable discovery. No amount of content fixes it,
    and teams often spend weeks adding pages before noticing.
  </Step>

  <Step title="Write short, direct answers">
    Paste plain text. You are writing for retrieval, not for a brochure.

    **Good:**

    ```
    Shipping outside India

    We ship to Nepal, Sri Lanka and Bangladesh. Delivery is 7–10 working days
    and costs ₹1,200 flat. We do not ship anywhere else outside India.
    ```

    **Bad:**

    ```
    We're proud to serve customers across the subcontinent and are always
    exploring new markets. Contact us to find out more!
    ```

    The second one answers nothing, and the agent will correctly keep saying it
    does not know.
  </Step>

  <Step title="Test the exact question">
    In the Playground, type the question **as the customer typed it** — from the
    report, misspellings and all. Not your tidied-up version of it.
  </Step>

  <Step title="Come back next week">
    The list changes as customers ask new things. Half an hour a week keeps
    "found an answer" climbing.
  </Step>
</Steps>

## The other report

**What people ask most** is grouped by exact wording, so the same question asked
two ways appears twice.

It is frequently a surprise to whoever wrote the website — the thing customers
ask constantly is often not the thing the homepage leads with. That is worth
acting on well beyond the agent.

## Reading the numbers honestly

**Found an answer** is the percentage of knowledge searches that returned
something. It is not a satisfaction score, and 100% is not the target — an agent
that never says "I don't know" is usually one that has been told to guess.

**Needed a person** is not a failure metric either. A business with nobody
watching the inbox should turn escalation off entirely; for everyone else, it is
the number that says whether the setup is working.

<Tip>
  Adding one well-written paragraph that answers a question asked 40 times a
  month beats indexing another 200 pages of your site. The gaps report tells you
  which paragraph.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.