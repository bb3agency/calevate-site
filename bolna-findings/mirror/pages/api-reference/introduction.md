> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna API Documentation

> Use and leverage Bolna Voice AI using APIs through HTTP requests from any language in your applications and workflows.

## What is the Bolna API?

The Bolna API enables you to programmatically create, configure, and manage Voice AI agents from your own applications. Whether you are building complex workflows, automating customer support, or integrating voice capabilities into your existing products, our REST API provides everything you need.

The API uses predictable, resource-oriented URLs, accepts JSON-encoded request bodies, returns JSON-encoded responses, and uses standard HTTP response codes and authentication.

<Warning>
  You must have an active Bolna account to generate and use API keys. If you don't have one, [sign up here](https://platform.bolna.ai).
</Warning>

***

## Authentication

All Bolna API endpoints require authentication using an API key. You must include this key in the `Authorization` header of all your HTTP requests using the `Bearer` scheme.

### How to generate an API Key

<Steps>
  <Step title="Navigate to Developers settings">
    Log in to the [Bolna Dashboard](https://platform.bolna.ai). From the left sidebar navigation menu, select the **Developers** tab.

    <Frame caption="Navigate to the Developers tab in the Bolna Dashboard">
      <img src="https://mintcdn.com/bolna-54a2d4fe/KVM5oeBM7OA9W3zw/images/api_introduction_1.1.png?fit=max&auto=format&n=KVM5oeBM7OA9W3zw&q=85&s=e1aa969eb4e7ced56db0cda2d656f1c2" alt="Bolna dashboard navigation showing the Developers tab" width="1900" height="1112" data-path="images/api_introduction_1.1.png" />
    </Frame>
  </Step>

  <Step title="Create a new API Key">
    Click the **Create a new API Key** button to generate your unique authentication credentials.

    <Frame caption="Click 'Create a new API Key' to generate your credentials">
      <img src="https://mintcdn.com/bolna-54a2d4fe/KVM5oeBM7OA9W3zw/images/api_introduction_2.1.png?fit=max&auto=format&n=KVM5oeBM7OA9W3zw&q=85&s=3aa3cc83e92bb7b7c94026bb765a6486" alt="Developers page showing the Create a new API Key button" width="1178" height="746" data-path="images/api_introduction_2.1.png" />
    </Frame>
  </Step>

  <Step title="Save your API Key securely">
    Your newly generated API key will be displayed in a pop-up modal. **Copy this key and save it securely.**

    <Frame caption="Copy and save your API Key - it won't be shown again">
      <img src="https://mintcdn.com/bolna-54a2d4fe/KVM5oeBM7OA9W3zw/images/api_introduction_3.1.png?fit=max&auto=format&n=KVM5oeBM7OA9W3zw&q=85&s=f094a2ec14a5e9cfa61e095aa285aaff" alt="API Key generation modal showing the newly created secret key" width="916" height="540" data-path="images/api_introduction_3.1.png" />
    </Frame>

    <Warning>
      **For your security, the API key will only be shown once.** If you lose your API key, you will need to delete it and generate a new one.
    </Warning>

    <Tip>
      API keys generated for a **Subaccount** will start with `sa-`.
    </Tip>
  </Step>
</Steps>

***
