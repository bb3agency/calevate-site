> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Telegram

> The quickest channel to connect — no approvals, no templates, no waiting.

Telegram is the one channel you can connect entirely by yourself, in about two
minutes. There is no business verification, no template approval and no 24-hour
window.

## Connect

<Steps>
  <Step title="Create a bot">
    Message [@BotFather](https://t.me/BotFather) on Telegram and send
    `/newbot`. Choose a display name and a username ending in `bot`.

    BotFather replies with a token that looks like
    `123456789:AAF-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.
  </Step>

  <Step title="Paste the token">
    On the agent's **Channels** page, open Telegram and paste it.

    <Warning>
      That token controls the bot completely. Treat it like a password — anyone
      holding it can read and send everything your bot does. It is sealed on
      arrival and never shown again.
    </Warning>
  </Step>

  <Step title="Say hello">
    Open your bot in Telegram and press **Start**. The agent answers with the
    same knowledge and instructions it uses everywhere else.
  </Step>
</Steps>

## What it can do

Text, buttons and images. Cards degrade to text with the buttons preserved.

Long replies are split across messages rather than truncated — Telegram rejects
a message over 4,096 characters outright, so splitting is the only behaviour
that does not silently lose the end of an answer.

## Opting out

A customer who asks the agent to stop is recorded as withdrawn, exactly as on
WhatsApp, and the agent stops replying to them.

## Two things it does not do

<Warning>
  **Telegram does not join a customer's identity.** There is no phone number
  unless the user volunteers a contact card, and matching on display name would
  merge two different people called Priya into one memory. Telegram threads are
  read once a customer has been linked by other means — they never do the
  linking.

  **Broadcasts do not send on Telegram.** A bot may message anyone who has
  pressed Start, so this is buildable; it is simply not built. Only WhatsApp
  carries a campaign today.
</Warning>

## Why start here

If you are evaluating the platform and do not yet have WhatsApp connected,
Telegram gives you a real, external channel to test against in minutes — a
proper end-to-end run rather than the Playground.

## Disconnecting

Disconnecting the bot stops it reaching you and frees the connection, so you can
put a different bot on the same agent afterwards.

<Check>
  **Your Telegram conversations and their messages stay.** Disconnecting removes
  the connection, not the history — the transcripts remain in your
  [inbox](/workspace/inbox) and in the record of what your customers were told.
</Check>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.