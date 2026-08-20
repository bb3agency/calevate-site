> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Integrating make.com with Bolna AI to send WhatsApp

> Learn how to send automated WhatsApp messages following a Bolna Voice AI phone call by integrating with Make.com.

<Tip>
  Connect Bolna with any of your favorite apps in just a few clicks using [official bolna's make.com integrations](https://www.make.com/en/integrations/bolna).
</Tip>

## Overview and requirements

1. Bolna account. You may create a free Bolna account by [signing up on Bolna](https://platform.bolna.ai/sign-up)
2. A Bolna AI agent which will be making the calls
3. Official Bolna's Make.com <b>`Bolna Watch end of Phone call`</b> trigger integration

## Steps to send WhatsApp after a Bolna AI phone call is completed

<Steps>
  <Step title="Create a webhook connection on Make.com">
    Follow the [webhook connection guide](/docs/tutorials/make-com/create-bolna-webhook-connection) to create a webhook connection and generate a webhook URL.

    <Frame caption="Adding &#x22;Bolna Watch end of Phone call&#x22; module to make.com">
      <img src="https://mintcdn.com/bolna-54a2d4fe/n6ISBDZpjo2_6G0U/images/tutorials/make-com/send_whatsapp_after_bolna_call_step_1.png?fit=max&auto=format&n=n6ISBDZpjo2_6G0U&q=85&s=49652b5c19631b1e979a1298a6f0454c" alt="Make.com scenario with Bolna Watch end of Phone call trigger module for automated WhatsApp notifications after Voice AI calls" width="1616" height="826" data-path="images/tutorials/make-com/send_whatsapp_after_bolna_call_step_1.png" />
    </Frame>
  </Step>

  <Step title="Add the WhatsApp module. For this tutorial, we've used Whatsable. You can use any other WhatsApp Provider as well.">
    <Frame caption="Adding Whatsable module with Bolna AI">
      <img src="https://mintcdn.com/bolna-54a2d4fe/n6ISBDZpjo2_6G0U/images/tutorials/make-com/send_whatsapp_after_bolna_call_step_2.png?fit=max&auto=format&n=n6ISBDZpjo2_6G0U&q=85&s=bd51686889427080ddcb3687cccaa5e6" alt="Whatsable module configuration in Make.com showing WhatsApp automation setup with Bolna Voice AI call completion data" width="1758" height="940" data-path="images/tutorials/make-com/send_whatsapp_after_bolna_call_step_2.png" />
    </Frame>

    Please note:

    1. If you want to use any extraction details, it will be provided as a JSON under `"extracted_data"` as shown below. Please refer to [extracting conversation data](/docs/guides/prompting/using-extractions) for more details and using it.

    ```json using extracted content theme={"system"}
    ...
    ...
    "extracted_data": {
      "salary_expected": "120K USD"
    },
    ...

    ```

    2. Any dynamic variables you pass for making the call, can be retrieved from `"context_details" > "recipient_data"` as shown below:

    ```json using user details theme={"system"}
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
    <Frame caption="Running Bolna + Whatsable scenario on make.com">
      <img src="https://mintcdn.com/bolna-54a2d4fe/n6ISBDZpjo2_6G0U/images/tutorials/make-com/send_whatsapp_after_bolna_call_step_3.png?fit=max&auto=format&n=n6ISBDZpjo2_6G0U&q=85&s=ddadbf624d74a6bf3c696f2c3d4e2860" alt="Make.com scenario execution showing successful Bolna Voice AI and Whatsable WhatsApp integration workflow testing" width="1290" height="764" data-path="images/tutorials/make-com/send_whatsapp_after_bolna_call_step_3.png" />
    </Frame>
  </Step>

  <Step title="Receiving the WhatsApp">
    <Frame caption="Make.com successfully sends the WhatsApp after Bolna AI call is completed">
      <img src="https://mintcdn.com/bolna-54a2d4fe/n6ISBDZpjo2_6G0U/images/tutorials/make-com/send_whatsapp_after_bolna_call_step_4.png?fit=max&auto=format&n=n6ISBDZpjo2_6G0U&q=85&s=64a078a80d1288bf649937694d3c13b7" alt="WhatsApp conversation showing automated message sent by Make.com after Bolna Voice AI call completion" width="1152" height="562" data-path="images/tutorials/make-com/send_whatsapp_after_bolna_call_step_4.png" />
    </Frame>
  </Step>
</Steps>
