> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Channels overview

> Where customers talk to your agent, and what each channel can carry.

A channel is a place a customer **talks to you**. There are four.

| Channel | Inbound | Agent replies | Broadcasts | Recognises signed-in customers |
| - | - | - | - | - |
| [Website widget](/channels/website) | Yes | Yes | Never — a campaign reaches somebody who is not there | Yes, [with signing](/install/signed-in-customers) |
| [WhatsApp](/channels/whatsapp) | Yes | Yes | Yes | Yes, by phone number |
| [Telegram](/channels/telegram) | Yes | Yes | Not built | No |
| [Voice](/channels/voice) | Yes, by phone | Yes, out loud | No — a call is not a broadcast | Yes, by phone number |

An agent has at most one channel of each kind.

<Note>
  **Shopify, WordPress and PrestaShop are not channels.** They are doors onto
  the website widget — ways to get it onto your pages without editing theme
  code. See [Put it on your site](/install/shopify).
</Note>

## One agent across all of them

The same knowledge, the same instructions, the same tools. You do not configure
a separate WhatsApp bot.

Each channel renders what it can. A card that appears as a rich card in the
website widget arrives as a native WhatsApp card, and where a channel cannot
render something it degrades to text rather than to a blank message.

## One customer across all of them

A person who asks on your website and then messages on WhatsApp is one contact
with one history — provided the two can be joined on evidence they did not
supply themselves. [How that works](/concepts#how-two-channels-become-one-person).

## What is not built

<Warning>
  * **Instagram and Messenger.** Not available. Meta's rules also forbid marketing
    content on those outside the 24-hour window, so a campaign lane would not
    exist there even if the channel did.
  * **Multi-channel campaigns.** The picker is real and only WhatsApp can send.
  * **WhatsApp calling.** Not yet. [Voice](/channels/voice) answers on a phone
    number and in the website widget today.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.