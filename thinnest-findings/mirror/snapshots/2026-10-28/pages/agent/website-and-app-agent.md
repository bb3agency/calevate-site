> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Website & app agent

> Let your agent see the screen your customer is on, fill it in, point at the right button and step in when they get stuck.

Switch this on and your agent stops being a chat in the corner. On your website
— and, with the mobile SDKs, inside your app — it can see the screen your
customer is on: the form, which fields are empty, the error under a field, the
buttons. It answers about what is in front of them, fills fields in, points at
the next step, and offers help on its own when someone gets stuck. By chat or by
voice.

## Switch it on

**1. Open the agent**

Go to **Agents**, open the agent on your website, and choose **Website & app**
under **Deploy**.

**2. Turn it on**

Switch on **Let the agent see and use the screen** and **Save**. If your chat
widget is already on your site, there is nothing else to add: it works on the
next page load.

**3. Choose what it may do**

Every action is on until you switch it off: point at a field or button, scroll
to it, put the cursor in a field, type into fields, choose from drop-downs,
tick boxes, press buttons and links, open another page of your site, and run
your own actions.

**4. Add the moments it steps in (optional)**

Under **When it steps in**, add a moment: what happens, on which pages, after
how long, and what the agent says. Set **At most … per visit**.

## What it always does — whatever you switch on

* It **never reads or fills** passwords, card numbers, CVV, OTP, Aadhaar or PAN
  fields.
* It sees **whether** a field is filled, not **what** is in it — unless you mark
  the field readable (below).
* PAN, Aadhaar and card numbers shown on the page are masked before anything
  leaves it, and page addresses leave without their query string.
* A button that **pays, submits or confirms** is pressed only after your customer
  taps **Allow** in the chat. If they tap **Not now**, the agent tells them so and
  leaves it to them.
* It never touches anything you mark off-limits.

## The moments it steps in

| Moment | What it means |
| - | - |
| The person has not done anything for a while | No typing, tapping or scrolling for the time you set |
| A field shows an error | An error stays on screen for the time you set |
| The same field fails twice | They fixed it, and it failed again |
| Clicks the same thing again and again | Three or more clicks on one spot within a second |
| Clicks something that does nothing | Nothing on the page changed after the click |
| Moves to leave the page | Desktop only: the pointer leaves the top of the window |
| Has been on the page for a while | Time on the page passes what you set |

**On pages containing** takes part of the page address (`checkout`, `/kyc`) or
the screen name your site sets (below). Leave it empty for every page. Each
moment shows at most once per page, never while the chat is open, and never more
than your per-visit limit. The message appears beside the chat button; a tap
opens the chat with the agent already talking.

## Tell it more (optional)

Add these after the widget tag:

```html theme={null}
<script>
  // The step the person is on, and facts the agent should know.
  AgentWidget.setScreen("kyc_address", { step: 3, product: "personal loan" });

  // Something that happened. The agent sees the last ten.
  AgentWidget.track("upload_failed");

  // An action of your own the agent may run on this page, with your customer's own session.
  AgentWidget.registerAction(
    "retry_upload",
    {
      description: "Retry uploading the document the customer chose",
      parameters: [{ name: "document", type: "string", description: "Which document", required: true }],
    },
    async ({ document }) => {
      const ok = await myApp.retryUpload(document);
      return { uploaded: ok };
    },
  );
</script>
```

Action names are lowercase with underscores. Whatever your function returns is
what the agent is told. Nothing your function does passes through ThinnestAI.

## Control element by element (optional)

```html theme={null}
<!-- Never read or touched by the agent -->
<div data-ta-mask>…</div>
<!-- Seen, but never typed into or clicked -->
<button data-ta-no-touch>Delete account</button>
<!-- The agent may read this field's value (hidden by default) -->
<input name="city" data-ta-allow />
<!-- Always ask before pressing / never ask -->
<button data-ta-confirm>Renew</button>
<button data-ta-safe>Next</button>
```

## Voice

If the agent takes calls on your website (**Voice → where it answers → Website**),
it can act on the screen during a call too. The call shrinks to a small bar with
the agent's name, a live caption, mute and hang-up, so your customer sees their
details go in while they talk. Anything that pays or submits still waits for
**Allow** in the chat.

## Mobile apps

SDKs for **Android, iOS, React Native and Flutter** are in early access. They show
the same agent — chat, voice, cards and forms — in a sheet over your app. Your app
describes each screen to the agent (its fields, their state and errors) and
carries out the actions in its own code. [Ask us for access](mailto:support@thinnest.ai).

## FAQ

> **Does it slow my website down?**
>
> The extra script loads only when this is switched on for the agent, and it
> reads the page only while the chat is open or a call is on.

> **Can the agent submit a form by itself?**
>
> It can fill the form. Pressing a button that submits, pays or confirms waits
> for your customer to tap Allow. To never let it press a particular button,
> mark it `data-ta-no-touch`.

> **Why does it say a field is filled but not what is in it?**
>
> By design: values stay on your customer's device. Add `data-ta-allow` to a
> field the agent may read, such as a city or plan name — never to anything
> personal.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.