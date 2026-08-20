> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Integrating make.com with Bolna AI to send SMS

> Discover how to automate SMS notifications after a Bolna Voice AI phone call by integrating with Make.com, improving follow-up communication.

<Tip>
  Connect Bolna with any of your favorite apps in just a few clicks using [official bolna's make.com integrations](https://www.make.com/en/integrations/bolna).
</Tip>

## Overview and requirements

1. Bolna account. You may create a free Bolna account by [signing up on Bolna](https://platform.bolna.ai/sign-up)
2. A Bolna Voice AI agent which will be making the calls
3. Official Bolna's Make.com <b>`Bolna Watch end of Phone call`</b> trigger integration

## Steps to send SMS after a Bolna AI phone call is completed

<Steps>
  <Step title="Create a webhook connection on Make.com">
    Follow the [webhook connection guide](/docs/tutorials/make-com/create-bolna-webhook-connection) to create a webhook connection and generate a webhook URL.

    <Frame caption="Adding &#x22;Bolna Watch end of Phone call&#x22; module to make.com">
      <img src="https://mintcdn.com/bolna-54a2d4fe/n6ISBDZpjo2_6G0U/images/tutorials/make-com/send_sms_after_bolna_call_step_1.png?fit=max&auto=format&n=n6ISBDZpjo2_6G0U&q=85&s=7f73569449e39c89fad81c904ab2af4d" alt="Make.com scenario with Bolna Watch end of Phone call trigger module for automated SMS notifications after Voice AI calls" width="1616" height="826" data-path="images/tutorials/make-com/send_sms_after_bolna_call_step_1.png" />
    </Frame>
  </Step>

  <Step title="Add the SMS module. For this tutorial, we've used Twilio. You can use any other SMS Provider as well.">
    <Frame caption="Adding Twilio SMS module with Bolna AI">
      <img src="https://mintcdn.com/bolna-54a2d4fe/n6ISBDZpjo2_6G0U/images/tutorials/make-com/send_sms_after_bolna_call_step_2.png?fit=max&auto=format&n=n6ISBDZpjo2_6G0U&q=85&s=afea4124bf4c83d1b8d24c8d891f23dc" alt="Twilio SMS module configuration in Make.com showing SMS automation setup with Bolna Voice AI call completion data" width="1774" height="892" data-path="images/tutorials/make-com/send_sms_after_bolna_call_step_2.png" />
    </Frame>

    Please note:

    1. If you want to use call summary, it will be provided under `"summary"` as shown below.

    ```json using call summary theme={"system"}
    ...
    ...
    "summary": "The conversation was between a user named Harry and an agent named Charles from Alexa. Charles initiated the call to assist Harry with inquiries about Apple Service Center. Harry asked for the location of the closest service center, and Charles informed about Apple Union Square, 300 Post Street San Francisco. After receiving the information, Harry indicated he had no further questions, and Charles offered to help in the future before concluding the call.",
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
    <Frame caption="Running Bolna + Twilio message scenario on make.com">
      <img src="https://mintcdn.com/bolna-54a2d4fe/n6ISBDZpjo2_6G0U/images/tutorials/make-com/send_sms_after_bolna_call_step_3.png?fit=max&auto=format&n=n6ISBDZpjo2_6G0U&q=85&s=caafd46d900126d5a7eff82daecc7d93" alt="Make.com scenario execution showing successful Bolna Voice AI and Twilio SMS integration workflow testing" width="1460" height="794" data-path="images/tutorials/make-com/send_sms_after_bolna_call_step_3.png" />
    </Frame>
  </Step>

  <Step title="Receiving the SMS">
    <Frame caption="Make.com successfully sends the SMS after Bolna AI call is completed">
      <img src="https://mintcdn.com/bolna-54a2d4fe/n6ISBDZpjo2_6G0U/images/tutorials/make-com/send_sms_after_bolna_call_step_4.png?fit=max&auto=format&n=n6ISBDZpjo2_6G0U&q=85&s=97b055f4ffbe066c260e293b9e56dbc1" alt="Mobile phone showing automated SMS notification sent by Make.com after Bolna Voice AI call completion" width="584" height="586" data-path="images/tutorials/make-com/send_sms_after_bolna_call_step_4.png" />
    </Frame>
  </Step>
</Steps>
