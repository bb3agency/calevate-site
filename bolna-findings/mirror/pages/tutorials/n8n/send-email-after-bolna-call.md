> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Integrating n8n with Bolna AI to send emails

> Discover how to automate email notifications after a Bolna Voice AI phone call using n8n for your automations and workflows.

<Tip>
  Connect Bolna with any of your favorite apps in just a few clicks using n8n's powerful and flexible workflow automation.
</Tip>

## Overview and requirements

1. A **Bolna account**. You may create a free Bolna account by [signing up on Bolna](https://platform.bolna.ai/sign-up).
2. A **Bolna Voice AI agent** which will be making the calls.
3. An **n8n instance** (cloud or self-hosted) with its **`Webhook`** trigger node.

## Steps to send emails after a Bolna AI phone call is completed

<Steps>
  <Step title="Create a webhook trigger on n8n">
    In your n8n canvas, add a **`Webhook`** node to start your workflow. Copy the **Test URL** provided by the node and paste it into the `webhook_url` field in your Bolna agent's configuration. Finally, click **"Listen for Test Event"** in n8n and make a test call with your Bolna agent to send sample data to your workflow.
  </Step>

  <Step title="Add the email module. For this tutorial, we've used Gmail. You can use any other Email Provider as well.">
    Add a **`Gmail`** node (or any other email node like `Send Email (SMTP)`) after the Webhook trigger. Connect your email account in the credentials section. Then, map the data received from the Bolna webhook into the email fields using n8n's expression editor.

    Please note:

    1. If you want to use any extraction details, it will be provided as a JSON under `"extracted_data"`. You can access it in n8n using an expression like `{{ $json.body.extracted_data.address }}`.

    ```json theme={"system"}
    ...
    ...
    "extracted_data": {
      "address": "Market street, San francisco",
      "salary_expected": "100k USD"
    },
    ...
    ```

    2. Any dynamic variables you pass for making the call can be retrieved from `"context_details" > "recipient_data"`. You can access the recipient's email with an expression like `{{ $json.body.context_details.recipient_data.email }}`.

    ```json theme={"system"}
    ...
    "context_details": {
      "recipient_data": {
        "name": "Harry",
        "email": "harry@hogwarts.com"
      },
      "recipient_phone_number": "+19876543210"
    },
    ...
    ```
  </Step>

  <Step title="Running & testing the entire scenario">
    Click **"Execute Workflow"** on your n8n canvas. The workflow will use the data captured from the last test call. You should see a green success indicator on both the Webhook and the Gmail nodes, confirming that the data was processed and the email was sent successfully.
  </Step>

  <Step title="Receiving the email">
    Check the recipient's inbox to confirm the email has been delivered. Verify that all the dynamic data, such as the recipient's name and the extracted call details, have been correctly populated in the email. Once confirmed, save and **activate your workflow**. Remember to replace the Test URL in Bolna with the **Production URL** from your n8n Webhook node for live calls.
  </Step>
</Steps>
