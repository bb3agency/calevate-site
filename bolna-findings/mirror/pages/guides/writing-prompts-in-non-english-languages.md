> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Writing Prompts in Non-English Languages

> Write multilingual prompts in native scripts for Bolna Voice AI. Ensure natural pronunciation & accurate responses in English, Hindi, Tamil, Telugu & more.

Bolna Voice AI agents have multilingual support and can have conversations in serveral languages ([see list of all support languages](/docs/customizations/multilingual-languages-support)). To ensure **natural speech output**, it is important to write your prompts in the **native script** of the target language, rather than phonetically using the English alphabet.

## Multilingual setup

Bolna supports multilingual configurations. You can add multiple languages to a single agent, set one as primary, and write a separate prompt for each.

> Example configurations:
>
> * English (Primary) + Hindi
> * English (Primary) + Hindi + Dutch
> * English (Primary) + French + Spanish

See the [Multilingual Support](/docs/customizations/multilingual-languages-support) guide for full setup details.

## Prompting for non-english language

If you want to switch languages dynamically you can instruct the prompt to follow the customer's language. For example, for Spanish you may write:

> You will keep your sentences short and crisp. You will never reply with more than 2 sentences at a time.
> You will stick to context throughout. You must speak in Spanish but if the customer wishes to communicate in English, you will immediately shift your language to English and then remain in english.
> Generate the text response in the same language as the customer.

***

## Write the prompt in the native script

Using the correct script:

* Enables more accurate pronunciation
* Helps the AI identify the intended language
* Improves contextual understanding and tone
* Prevents misclassification as English

## Tips for Writing in native scripts

* Use Google Input Tools or built-in language keyboards on your phone/laptop.
* For European languages, make sure to include accented characters (like é, ñ, ü, ¿, ç, etc.).
* Double-check spellings and punctuation using tools like [Google Translate](https://translate.google.com/), but avoid relying on it for full sentence correctness.

## Examples of prompts in native scripts

<Tabs>
  <Tab title="🇫🇷 French">
    ❌ Incorrect

    > Bonjour! Comment ca va? Nous allons commencer l'entretien maintenant.

    ✅ Correct

    > Bonjour ! Comment ça va ? Nous allons commencer l’entretien maintenant.

    <Tip>Notice the accents (ç, é, ’). These help the AI pronounce words like a native speaker.</Tip>
  </Tab>

  <Tab title="🇪🇸 Spanish">
    ❌ Incorrect

    > Hola! Como estas? Vamos a comenzar la entrevista ahora.

    ✅ Correct

    > ¡Hola! ¿Cómo estás? Vamos a comenzar la entrevista ahora.

    <Tip>Accents and inverted punctuation (¿, ¡) matter for tone and pronunciation accuracy.</Tip>
  </Tab>

  <Tab title="🇮🇳 Hindi (Devanagari Script)">
    ❌ Incorrect

    > Namaste! Aap kaise ho? Ham aapka interview lene wale hain.

    ✅ Correct

    > नमस्ते! आप कैसे हैं? हम आपका इंटरव्यू लेने वाले हैं।

    <Tip>Accents and inverted punctuation (¿, ¡) matter for tone and pronunciation accuracy.</Tip>
  </Tab>
</Tabs>

***

## Common Mistake to Avoid

Don’t write in "English-style" phonetic spelling for non-English prompts.

> ❌ Kaise ho? <br />
> ✅ कैसे हो?

> ❌ Como estas? <br />
> ✅ ¿Cómo estás?

## FAQs

<AccordionGroup>
  <Accordion title="How many languages can I add to one agent?">
    You can add multiple languages to a single agent. Set one as primary and add secondary languages as needed. Each language gets its own prompt tab in the [Agent Tab](/docs/agent-setup/agent-tab).
  </Accordion>

  <Accordion title="What if my customer switches languages mid-conversation?">
    Bolna agents can dynamically switch between any of the configured languages. Use the **Language Switching Instructions** field in the [Agent Tab](/docs/agent-setup/agent-tab) to define when the agent should switch. If a customer speaks a language not configured on the agent, it will fall back to the primary language.
  </Accordion>

  <Accordion title="Do I need to use formal or informal forms in prompts?">
    It depends on your audience and brand tone. Ensure your prompts reflect the appropriate politeness level (e.g., “vous” vs. “tu” in French, or “आप” vs. “तुम” in Hindi) for a consistent and professional experience.
  </Accordion>

  <Accordion title="How do I test the pronunciation?">
    Use Bolna's Preview Voice feature in \[Voice Labs]\[[https://platform.bolna.ai/voices](https://platform.bolna.ai/voices)] to test generated responses before finalizing your prompts. Adjust words and punctuation if needed for more natural pronunciation.
  </Accordion>
</AccordionGroup>
