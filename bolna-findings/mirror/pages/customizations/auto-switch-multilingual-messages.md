> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Auto-Detect and Switch Languages in Bolna Voice AI

> Learn how Bolna Voice AI automatically detects the caller's language and switches system messages like hangup, user online check, and tool call messages to match.

Bolna Voice AI automatically detects the language your callers speak and switches system messages to match. No manual intervention needed. The agent analyzes the conversation and delivers the right message in the right language.

<CardGroup cols={3}>
  <Card title="User Online Check" icon="user-check">
    "Are you still there?" plays in the caller's detected language
  </Card>

  <Card title="Call Hangup" icon="phone">
    Farewell message delivered in the detected language
  </Card>

  <Card title="Tool Call Wait" icon="gear">
    "Please wait" messages during API calls adapt to the language
  </Card>
</CardGroup>

***

## How Detection Works

<Steps>
  <Step title="Conversation Begins">
    The agent starts in the primary language configured in the [Audio Tab](/docs/agent-setup/audio-tab).
  </Step>

  <Step title="Language Analysis">
    After **3 conversation turns**, Bolna analyzes the caller's transcripts to identify the dominant language being spoken.
  </Step>

  <Step title="Auto-Switch">
    Once detected, all configured system messages switch to that language for the rest of the call.
  </Step>
</Steps>

<Info>
  Detection waits for 3 turns to gather enough context for accurate identification. This keeps it fast while avoiding false matches early in the call.
</Info>

***

## Supported Message Types

### User Online Check Message

When the agent checks if a caller is still on the line after a period of silence, it sends a configurable message. Add variants in multiple languages and Bolna picks the right one automatically.

<Frame caption="Multilingual user online check messages configured for English, Hindi, Gujarati, Bengali, and Tamil">
  <img src="https://mintcdn.com/bolna-54a2d4fe/RNxn2cW88Bvahom0/images/auto_switch_language_check_user_online.png?fit=max&auto=format&n=RNxn2cW88Bvahom0&q=85&s=1ff45f2ca0ad19744c01b441dedb3b27" alt="User online detection settings with multilingual message fields for English, Hindi, Gujarati, Bengali, and Tamil" width="1776" height="930" data-path="images/auto_switch_language_check_user_online.png" />
</Frame>

```json theme={"system"}
{
  "check_user_online_message": {
    "en": "Hey, are you still there?",
    "hi": "क्या आप अभी भी वहाँ हैं?",
    "ta": "வணக்கம், நீங்கள் இன்னும் இணைப்பில் இருக்கிறீர்களா?",
    "bn": "নমস্কার, আপনি কি এখনও লাইনে আছেন?"
  }
}
```

***

### Call Hangup Message

When the agent ends a call, it delivers a closing message. Configure multilingual variants so callers hear a natural farewell in their language.

<Frame caption="Multilingual call hangup messages configured for English, Hindi, Bengali, and Tamil">
  <img src="https://mintcdn.com/bolna-54a2d4fe/RNxn2cW88Bvahom0/images/auto_switch_language_hangup_message.png?fit=max&auto=format&n=RNxn2cW88Bvahom0&q=85&s=da196d74561104a1d6ced68d94646c93" alt="Call settings showing multilingual hangup message fields for English, Hindi, Bengali, and Tamil" width="1776" height="1048" data-path="images/auto_switch_language_hangup_message.png" />
</Frame>

```json theme={"system"}
{
  "call_hangup_message": {
    "en": "Thank you for calling. Goodbye!",
    "hi": "कॉल करने के लिए धन्यवाद। अलविदा!",
    "bn": "কলটি এখন কেটে যাবে। ধন্যবাদ এবং নমস্কার!"
  }
}
```

***

### Function Tool Call Messages

When the agent executes a tool or API call, it plays a brief "please wait" message. This message can also be configured per language.

<Frame caption="Multilingual pre-call messages for custom function tools in English and Hindi">
  <img src="https://mintcdn.com/bolna-54a2d4fe/RNxn2cW88Bvahom0/images/auto_switch_language_function_tools.png?fit=max&auto=format&n=RNxn2cW88Bvahom0&q=85&s=75d671c0af4a2352098c37d12710e468" alt="Custom function configuration showing pre_call_message JSON with English and Hindi variants" width="1776" height="1048" data-path="images/auto_switch_language_function_tools.png" />
</Frame>

```json theme={"system"}
{
  "pre_call_message": {
    "en": "Just give me a moment, I'll be back with you.",
    "hi": "कृपया थोड़ा समय दीजिए, मैं पता करके बताता हूँ।"
  }
}
```

***

## Fallback Behavior

When selecting a message, Bolna follows a three-step fallback:

| Priority                 | What happens                                                              |
| ------------------------ | ------------------------------------------------------------------------- |
| **1. Detected language** | Uses the message in the caller's detected language                        |
| **2. English**           | Falls back to the `en` variant if the detected language is not configured |
| **3. First available**   | Uses the first language in the configuration if neither is found          |

<Tip>
  Always configure an `en` (English) variant as a safe fallback for every message type.
</Tip>

***

## Supported Languages

Auto-detection supports all languages available in Bolna, identified by their ISO 639-1 codes.

| Code | Language | Code | Language | Code | Language  |
| ---- | -------- | ---- | -------- | ---- | --------- |
| `en` | English  | `hi` | Hindi    | `bn` | Bengali   |
| `ta` | Tamil    | `te` | Telugu   | `mr` | Marathi   |
| `gu` | Gujarati | `kn` | Kannada  | `ml` | Malayalam |
| `pa` | Punjabi  | `ur` | Urdu     | `as` | Assamese  |

<Info>
  For the full list of supported languages, see the [Multilingual Support](/docs/customizations/multilingual-languages-support) guide.
</Info>

***

## Best Practices

<CardGroup cols={2}>
  <Card title="Consistent Coverage" icon="list-check">
    Add message variants for every language your agent supports. Gaps lead to unexpected fallbacks.
  </Card>

  <Card title="Culturally Appropriate" icon="globe">
    Write messages that feel natural in each language. Avoid direct translations.
  </Card>

  <Card title="Native Script" icon="pen-nib">
    Always use the language's native script. "धन्यवाद" not "Dhanyavaad".
  </Card>

  <Card title="Test with Speakers" icon="flask">
    Verify messages sound natural by testing with native speakers of each language.
  </Card>
</CardGroup>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Multilingual Support" icon="earth-americas" href="/docs/customizations/multilingual-languages-support">
    Full guide to setting up multilingual agents
  </Card>

  <Card title="Non-English Prompts" icon="language" href="/docs/guides/writing-prompts-in-non-english-languages">
    Best practices for writing prompts in native scripts
  </Card>

  <Card title="Custom Function Calls" icon="code" href="/docs/tool-calling/custom-function-calls">
    Configure pre-call messages for API tools
  </Card>

  <Card title="Engine Tab" icon="gear" href="/docs/agent-setup/engine-tab">
    Configure user online detection and timeouts
  </Card>
</CardGroup>
