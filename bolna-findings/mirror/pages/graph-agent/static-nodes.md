> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Static Nodes & Silence Repeat

> Pre-cached audio messages that play in 50ms with zero LLM cost, plus auto-replay on user silence with deterministic escalation.

Many nodes in a flow always say the same thing: greetings, hold messages, confirmations, goodbyes. A static node pre-renders the audio for that message when the agent is saved and plays it back from cache at runtime. No LLM call. No TTS call. No latency.

`repeat_after_silence_seconds` is a related setting that auto-replays a node after N seconds of user silence and exposes a `_silence_repeats` counter so expression edges can escalate after a few silent rounds (offer help, transfer, hang up).

## Latency and cost

| Node type   | Latency                     | Cost per turn               |
| ----------- | --------------------------- | --------------------------- |
| LLM node    | \~800ms (LLM + TTS + audio) | LLM tokens + TTS characters |
| Static node | \~50ms (cached audio)       | Zero                        |

***

## Configuring a static node

Set `node_type` to `"static"` and provide `static_message`:

```json theme={"system"}
{
  "id": "greeting",
  "node_type": "static",
  "static_message": "Hello! Thank you for calling Acme. How can I help you today?",
  "edges": [
    { "to_node_id": "main_menu", "condition": "User responds with a request" }
  ]
}
```

That's it. The audio is pre-generated using the agent's configured TTS voice when the agent is saved, then served from cache on every call.

### Field reference

| Field                          | Type                       | Required                         | What it does                                                                                                                                                                                                                                    |
| ------------------------------ | -------------------------- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `node_type`                    | `"llm"` or `"static"`      | No (defaults to `"llm"`)         | Controls whether the node calls the LLM or plays cached audio.                                                                                                                                                                                  |
| `static_message`               | string or per-language map | Yes when `node_type == "static"` | The exact text to speak. Accepts a single string, or a `{ "language_code": "text" }` map for multilingual agents (see [Multilingual static messages](#multilingual-static-messages)). Audio is pre-generated from this when the agent is saved. |
| `repeat_after_silence_seconds` | number                     | No                               | If set, replays the node's response after this many seconds of user silence. Works on **both** static and LLM nodes. In the editor, this is the **Auto-replay on silence** toggle in the node inspector.                                        |

<Note>
  All three fields are optional with safe defaults. Existing graph agents that don't use any of them behave exactly as before.
</Note>

***

## Multilingual static messages

For a multilingual agent, `static_message` can be a per-language map instead of a single string. At runtime the node speaks the variant that matches the caller's active language, and the platform pre-generates a separate cached clip for each language using that language's voice.

```json theme={"system"}
{
  "id": "clinic_hours",
  "node_type": "static",
  "static_message": {
    "en": "Our clinic is open Monday to Saturday, 9 AM to 8 PM.",
    "hi": "हमारा क्लिनिक सोमवार से शनिवार, सुबह 9 से रात 8 बजे तक खुला रहता है।",
    "ta": "எங்கள் மருத்துவமனை திங்கள் முதல் சனி வரை காலை 9 மணி முதல் இரவு 8 மணி வரை திறந்திருக்கும்."
  },
  "edges": [
    { "to_node_id": "main_menu", "condition_type": "unconditional" }
  ]
}
```

Use the same two-letter language codes as your agent's [multilingual configuration](/docs/customizations/multilingual-config-reference). When the caller's language switches mid-call ([auto-switch](/docs/customizations/auto-switch-multilingual-messages)), the next static node automatically plays the matching-language clip. This is the same `{ "language_code": "text" }` format used by system messages like `call_hangup_message` and `check_user_online_message`.

<Note>
  A plain-string `static_message` keeps working unchanged, so add a map only when you want per-language audio.
</Note>

### How the multilingual audio is built

When you save the agent, the platform pre-generates one cached clip per language variant, each rendered with that language's configured voice. At call time the clip for the active language streams from cache with the same instant playback and zero cost as a single-language static node. If a language has no dedicated voice in your multilingual settings, its clip falls back to the agent's primary voice.

***

## Silence repeat

When `repeat_after_silence_seconds` is set and the user goes quiet:

1. The silence timer fires after the configured seconds.
2. `_silence_repeats` increments by 1.
3. Expression edges are evaluated. If one matches `_silence_repeats`, the agent transitions.
4. Otherwise the node replays. A static node plays the same cached audio (zero cost). An LLM node regenerates with `[silence]` in the conversation history and rephrases naturally.
5. `_silence_repeats` resets to `0` on any transition out of the node.

***

## Example: greeting with silence fallback

Play a greeting. If the user is silent, repeat up to 3 times, then hang up.

```json theme={"system"}
{
  "id": "greeting",
  "node_type": "static",
  "static_message": "Hello! Thank you for calling. How can I help you today?",
  "repeat_after_silence_seconds": 8,
  "edges": [
    { "to_node_id": "main_menu", "condition": "User responds with a request" },
    {
      "to_node_id": "goodbye",
      "condition_type": "expression",
      "expression": {
        "conditions": [
          { "variable": "_silence_repeats", "operator": "gte", "value": 3 }
        ]
      }
    }
  ]
}
```

What happens:

* Cached audio plays instantly.
* User silent for 8s, audio replays (`_silence_repeats = 1`).
* Still silent, replays (`_silence_repeats = 2`).
* Still silent, replays (`_silence_repeats = 3`), expression matches, transitions to `goodbye`.

***

## Example: LLM node with silence nudge

The same pattern works on LLM nodes. The LLM sees `[silence]` in conversation history and rephrases without any extra prompt engineering on your part.

```json theme={"system"}
{
  "id": "collect_email",
  "prompt": "Ask the user for their email address politely.",
  "repeat_after_silence_seconds": 10,
  "edges": [
    {
      "to_node_id": "confirm",
      "condition": "User shared an email",
      "parameters": { "email": "string" }
    },
    {
      "to_node_id": "goodbye",
      "condition_type": "expression",
      "expression": {
        "conditions": [
          { "variable": "_silence_repeats", "operator": "gte", "value": 3 }
        ]
      }
    }
  ]
}
```

The LLM might say "Could you share your email?" first, then "Sorry, I didn't catch that, could you tell me your email?" on the next silence, then transition to goodbye after the third.

***

## When the cache is built

Audio for every static node is generated when you save the agent, using the agent's configured TTS voice. At call time the cached audio is streamed directly, no LLM or TTS call.

If you change `static_message` later, re-save the agent so the cache regenerates with the new text.
