> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Why am I receiving SIP response codes 480 or 486?

> SIP 480 and 486 errors on Vobiz indicate the callee is unavailable or busy - learn what triggers each code, how to read CDRs, and how to debug carrier spam blocks.

When routing calls via Voice XML or SIP trunks, you may encounter error codes in your Call Detail Records (CDRs) or webhook events. Codes `480` and `486` generally indicate transient availability issues on the recipient's telecom side rather than a platform failure.

## 486 - Busy Here

This response is triggered when the callee's device is already on another call and call waiting is not enabled, or when the recipient has explicitly rejected the call by pressing the reject button. In SIP terms, the endpoint returned a `Busy Here` response, terminating the sequence.

## 480 - Temporarily Unavailable

This response occurs when the receiving device cannot be reached. Common scenarios include:

* The user's mobile device is switched off entirely or the battery died.
* The user is outside of their carrier's cellular coverage area.
* The user has placed their device in Airplane mode or "Do Not Disturb" (DND).
* The network operator experienced a routing timeout before the device could answer.

## Debugging & Network Blocks

If you repeatedly see `480` or `486` against multiple distinct numbers on a specific carrier, it is likely that the local network operator's spam filters have temporarily blocked your caller ID.

<Warning>
  If you suspect a carrier-level block, please pause dialing attempts for several hours or contact our support team. We can investigate upstream carrier PCAP traces to confirm whether the rejection was user-driven or network-driven.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.