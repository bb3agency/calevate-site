> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Supported Providers for Bolna Voice AI

> Explore the list of providers supported by Bolna Voice AI, including integrations for telephony, transcription, and text-to-speech services to lower your costs

<Note>
  We don't charge for any usage for providers that you have connected to Bolna.<br />

  We connect all your `Provider` accounts securely via using [infisical](https://infisical.com/).
</Note>

### Steps to add your own Provider credentials:

<Steps>
  <Step title="First step">
    Login to the dashboard at [https://platform.bolna.ai](https://platform.bolna.ai)
  </Step>

  <Step title="Second step">
    Navigate to `Developers` tab from the left menu bar
  </Step>

  <Step title="Third step">
    Head over to the `Provider Keys` tab
  </Step>

  <Step title="Fourth step">
    Click the button `Add Provider Key` to your Provider key-value pair
  </Step>

  <Step title="Fifth step">
    Save your Provider
  </Step>
</Steps>

We currently have the following providers which you can connect to Bolna.
All these keys **must** be added for the respective provider.

<Tabs>
  <Tab title="Telephony">
    <Accordion title="Twilio">
      | Property              | Description         |
      | --------------------- | ------------------- |
      | `TWILIO_ACCOUNT_SID`  | Twilio account SID  |
      | `TWILIO_AUTH_TOKEN`   | Twilio token        |
      | `TWILIO_PHONE_NUMBER` | Twilio phone number |

      For creating a free Twilio Account you can checkout their blog [How to Work with your Free Twilio Trial Account](https://www.twilio.com/docs/messaging/guides/how-to-use-your-free-trial-account)
    </Accordion>

    <Accordion title="Plivo">
      | Property             | Description        |
      | -------------------- | ------------------ |
      | `PLIVO_AUTH_ID`      | Plivo auth ID      |
      | `PLIVO_AUTH_TOKEN`   | Plivo auth token   |
      | `PLIVO_PHONE_NUMBER` | Plivo phone number |
    </Accordion>

    <Accordion title="Vobiz">
      | Property             | Description        |
      | -------------------- | ------------------ |
      | `VOBIZ_AUTH_ID`      | Vobiz Auth ID      |
      | `VOBIZ_AUTH_TOKEN`   | Vobiz Auth Token   |
      | `VOBIZ_PHONE_NUMBER` | Vobiz phone number |
    </Accordion>

    <Accordion title="Exotel">
      | Property                 | Description                    |
      | ------------------------ | ------------------------------ |
      | `EXOTEL_API_KEY`         | Exotel API Key                 |
      | `EXOTEL_API_TOKEN`       | Exotel API token               |
      | `EXOTEL_ACCOUNT_SID`     | Exotel Account SID             |
      | `EXOTEL_DOMAIN`          | Exotel Domain                  |
      | `EXOTEL_PHONE_NUMBER`    | Exotel phone number            |
      | `EXOTEL_OUTBOUND_APP_ID` | Exotel Outbound Application ID |
      | `EXOTEL_INBOUND_APP_ID`  | Exotel Inbound Application ID  |
    </Accordion>
  </Tab>

  <Tab title="LLMs">
    <Accordion title="OpenAI">
      | Property | Description         |
      | -------- | ------------------- |
      | `OPENAI` | Your OpenAI API key |
    </Accordion>

    <Accordion title="OpenRouter">
      | Property     | Description             |
      | ------------ | ----------------------- |
      | `OPENROUTER` | Your OpenRouter API key |
    </Accordion>

    <Accordion title="Azure OpenAI">
      | Property                   | Description                  |
      | -------------------------- | ---------------------------- |
      | `AZURE_OPENAI_API_KEY`     | Your Azure API key           |
      | `AZURE_OPENAI_MODEL`       | Your Azure OpenAI model      |
      | `AZURE_OPENAI_API_BASE`    | Your Azure URL               |
      | `AZURE_OPENAI_API_VERSION` | Your Azure Model API version |
    </Accordion>

    <Accordion title="Google Gemini">
      | Property | Description                |
      | -------- | -------------------------- |
      | `GOOGLE` | Your Google Gemini API key |
    </Accordion>

    <Accordion title="Custom LLM">
      For custom llm simply keep provider in the `llm_agent` key as `custom` and add a openai compatible `base_url`

      #### Example LLM Agent key for the

      ```
      "llm_agent": {
        			"max_tokens": 100.0,
        			"presence_penalty": 0.0,
        			"base_url": "https://custom.llm.model/v1",
        			"extraction_details": null,
        			"top_p": 0.9,
        			"agent_flow_type": "streaming",
        			"request_json": false,
        			"routes": null,
        			"min_p": 0.1,
        			"frequency_penalty": 0.0,
        			"stop": null,
        			"provider": "custom",
        			"top_k": 0.0,
        			"temperature": 0.2,
        			"model": "custom-llm-model",
        			"family": "llama"
        		}
      ```
    </Accordion>
  </Tab>

  <Tab title="Synthesizer">
    <Accordion title="Elevenlabs">
      | Property     | Description             |
      | ------------ | ----------------------- |
      | `ELEVENLABS` | Your Elevenlabs API key |
    </Accordion>

    <Accordion title="Cartesia">
      | Property   | Description           |
      | ---------- | --------------------- |
      | `CARTESIA` | Your Cartesia API key |
    </Accordion>

    <Accordion title="Sarvam">
      | Property | Description         |
      | -------- | ------------------- |
      | `SARVAM` | Your Sarvam API key |
    </Accordion>

    <Accordion title="Smallest">
      | Property   | Description           |
      | ---------- | --------------------- |
      | `SMALLEST` | Your Smallest API key |
    </Accordion>
  </Tab>

  <Tab title="Transcriber">
    <Accordion title="Deepgram">
      | Property   | Description       |
      | ---------- | ----------------- |
      | `DEEPGRAM` | Your Deepgram key |
    </Accordion>

    <Accordion title="Soniox">
      | Property | Description     |
      | -------- | --------------- |
      | `SONIOX` | Your Soniox key |
    </Accordion>
  </Tab>
</Tabs>
