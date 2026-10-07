> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Send your first broadcast

> Start to finish, with the mistakes that cost real money marked.

Your first broadcast is the one most likely to go wrong, and the errors are
expensive: WhatsApp charges for every marketing send, and a bad one costs you
the number's reputation as well.

Work through this in order.

<Steps>
  <Step title="Check you can send at all">
    Three things, and each screen tells you what the next needs:

    * WhatsApp connected — **Connect WhatsApp** in the sidebar
    * At least one **approved** template
    * Contacts with `granted` consent and a phone number

    If **Contacts** shows zero consented people, stop here. A broadcast with an
    empty audience is not a broadcast.
  </Step>

  <Step title="Write a marketing template">
    ```
    Hi {{1}}, our monsoon sale is on — 25% off everything until Sunday.
    ```

    <Warning>
      **Category it as marketing.** It is promotional, and labelling it utility
      to bypass consent is the fastest route to getting your number restricted
      by Meta. Utility is for order confirmations and delivery updates, not for
      anything you would call a broadcast.
    </Warning>

    Submit and wait for approval — usually minutes, always Meta's decision.
  </Step>

  <Step title="Send to yourself first">
    Before any audience, use the [API](/api-reference/send-message) or a
    one-person audience to send it to your own number.

    ```bash theme={null}
    curl -X POST https://app.thinnest.ai/api/v1/messages \
      -H "Authorization: Bearer $THINNEST_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "to": "919876543210",
        "template": "monsoon_sale_v1",
        "variables": ["Priya"]
      }'
    ```

    Read it on a phone. Templates that look fine in an editor routinely arrive
    with a blank where a name should be, or a link that wraps badly.
  </Step>

  <Step title="Choose the audience">
    Four lists, ordered by risk, each showing its count before you commit.

    | Audience | Start here? |
    | - | - |
    | **WhatsApp opted-in** | **Yes.** People who reached you on WhatsApp and consented |
    | All consented | Once the first one goes well |
    | Imported | Only if you are certain how that consent was collected |
    | Everyone | Rarely what you want |

    <Tip>
      Start with the narrowest list. A first broadcast to 40 engaged people
      teaches you more than one to 4,000 strangers, and costs less to get wrong.
    </Tip>
  </Step>

  <Step title="Bind the variables">
    `{{1}}` to the contact's name. A template with a placeholder cannot go out
    with it empty, so this is enforced rather than trusted.
  </Step>

  <Step title="Send, and leave the tab open">
    <Warning>
      **A send started in the console runs from your browser.** Close the tab and
      the send pauses.

      It does not lose anything — each recipient is its own row, so it resumes
      and nobody is messaged twice. But it will not finish while the tab is
      closed.

      **Schedule it instead** if you want to walk away. A scheduled send has no
      tab and needs none.
    </Warning>
  </Step>

  <Step title="Read the results properly">
    The broadcast's page separates four different facts:

    | | Means |
    | - | - |
    | **Sent** | WhatsApp accepted it. **Not** that it arrived |
    | **Delivered** | It reached the handset |
    | **Read** | They opened it |
    | **Refused** | It did not go, with Meta's own reason |

    Read the refusals. They are grouped by reason, and they are the most useful
    part of the page — a batch of "invalid number" says something about your
    contact data that no success count will.
  </Step>
</Steps>

## After the first one

* **Delivered but not read** is a timing problem. Try a different hour.
* **Read but no replies** is a message problem, not a reach problem.
* **Refused for consent** is correct behaviour. Those people opted out.

## What will not work

<Warning>
  * **Multi-channel.** The picker is real; only WhatsApp sends. Telegram could and
    is not built.
  * **A/B testing.** Not built.
  * **Sending to a bought list.** Consent is enforced where it cannot be
    bypassed, and Meta punishes it harder than we do.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.