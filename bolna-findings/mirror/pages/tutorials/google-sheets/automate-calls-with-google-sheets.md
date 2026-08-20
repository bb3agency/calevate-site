> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Automate Outbound Calls with Bolna AI and Google Sheets

> Build a call automation pipeline with Bolna Voice AI and Google Sheets. Trigger calls from a spreadsheet, track status via webhooks, and capture transcripts.

## What You'll Build

A lightweight, serverless pipeline that connects Google Sheets directly to the Bolna Voice AI platform. You will write a few functions in Google Apps Script that:

* **Trigger outbound calls** by reading phone numbers from your spreadsheet
* **Track call progress** in real time as Bolna sends webhook updates
* **Capture call data** like status, duration, transcripts, and errors back into the same sheet

This pattern works for any outbound use case, whether it is product announcements, feedback surveys, appointment reminders, onboarding calls, or lead qualification.

<Info>
  This tutorial uses the [Bolna Make a Call API](/docs/api-reference/calls/make) and [webhooks](/docs/guides/post-call/polling-call-status-webhooks) with Google Apps Script. No external automation platforms or servers are required.
</Info>

***

## Prerequisites

<CardGroup cols={2}>
  <Card title="Bolna Account" icon="user-plus" href="https://platform.bolna.ai/sign-up">
    Free trial includes \$5 in credits
  </Card>

  <Card title="A Voice AI Agent" icon="robot" href="/docs/getting-started/agent-creation">
    Create or pick any agent from the Agent Library
  </Card>

  <Card title="Bolna API Key" icon="key" href="/docs/api-reference/introduction">
    Generate one from the Developers page in your dashboard
  </Card>

  <Card title="Google Account" icon="google" href="https://sheets.google.com">
    Access to Google Sheets and Apps Script
  </Card>
</CardGroup>

You will also need your **Agent ID**, which is visible next to the agent name on the [Agent Setup](/docs/agent-setup/overview) page.

<Warning>
  Trial accounts can only call **verified numbers**. Add yours via **User Profile → Verified Numbers** on the Bolna dashboard before testing.
</Warning>

***

## Step 1: Prepare Your Google Sheet

Create a new spreadsheet and add these column headers in row 1:

| Column | Header           | Purpose                                                         |
| ------ | ---------------- | --------------------------------------------------------------- |
| A      | **Phone Number** | Numbers to call                                                 |
| B      | **Execution ID** | Returned by the API, used to link webhook updates to each row   |
| C      | **Status**       | `scheduled` → `queued` → `in-progress` → `completed` / `failed` |
| D      | **Duration**     | Conversation length in seconds                                  |
| E      | **Transcript**   | Full call transcript                                            |
| F      | **Timestamp**    | Last status update time                                         |
| G      | **Error**        | Error details, if any                                           |

Fill column A with the phone numbers you want to call. Leave all other columns empty as the script will populate them automatically.

***

## Step 2: Open the Apps Script Editor

Go to **Extensions → Apps Script** in your Google Sheet. This opens a cloud-based JavaScript editor where all your automation code will live.

<Tip>
  All code below goes into the default `Code.gs` file. You can optionally split it across multiple `.gs` files. Apps Script treats them all as a single project.
</Tip>

***

## Step 3: Configure Your Credentials

Add the following constants at the top of `Code.gs`. Replace the placeholder values with your actual details:

```javascript theme={"system"}
// Your spreadsheet ID (the string between /d/ and /edit in the sheet URL)
const SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID';
const SHEET_NAME = 'Sheet1';

// Bolna credentials
const BOLNA_API_KEY = 'YOUR_BOLNA_API_KEY';
const BOLNA_AGENT_ID = 'YOUR_BOLNA_AGENT_ID';
const BOLNA_API_BASE = 'https://api.bolna.ai';

// Column index map (0-based) for clean references
const COL = {
  PHONE: 0,
  EXEC_ID: 1,
  STATUS: 2,
  DURATION: 3,
  TRANSCRIPT: 4,
  TIMESTAMP: 5,
  ERROR: 6,
};
```

***

## Step 4: Write the Call Functions

Add these three functions to `Code.gs`:

<AccordionGroup>
  <Accordion title="normalizePhone: Format phone numbers">
    Cleans and converts raw phone input into international format so calls don't fail on formatting issues.

    ```javascript theme={"system"}
    function normalizePhone(raw) {
      let phone = String(raw).replace(/[^\d+]/g, '');
      if (phone.startsWith('+')) return phone;
      if (phone.length === 10) return '+91' + phone; // adjust country code as needed
      return '+' + phone;
    }
    ```

    <Tip>
      Modify the country code (`+91`) to match your region, or remove the fallback entirely if all your numbers are already in international format.
    </Tip>
  </Accordion>

  <Accordion title="triggerCall: Place a single call via the Bolna API">
    Sends a POST request to the [Make a Call endpoint](/docs/api-reference/calls/make) and returns the `execution_id` that uniquely identifies this call.

    ```javascript theme={"system"}
    function triggerCall(phone) {
      const res = UrlFetchApp.fetch(`${BOLNA_API_BASE}/call`, {
        method: 'post',
        contentType: 'application/json',
        headers: { Authorization: `Bearer ${BOLNA_API_KEY}` },
        payload: JSON.stringify({
          agent_id: BOLNA_AGENT_ID,
          recipient_phone_number: phone,
        }),
        muteHttpExceptions: true,
      });

      const body = JSON.parse(res.getContentText());
      if (!body.execution_id) throw new Error('No execution_id returned');
      return body.execution_id;
    }
    ```
  </Accordion>

  <Accordion title="runBolnaCalls: Loop through the sheet and trigger all calls">
    Iterates over every row, skips rows that already have a status, and triggers a call for each new phone number.

    ```javascript theme={"system"}
    function runBolnaCalls() {
      const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(SHEET_NAME);
      const rows = sheet.getDataRange().getValues();

      for (let i = 1; i < rows.length; i++) {
        const phoneRaw = rows[i][COL.PHONE];
        const status = rows[i][COL.STATUS];

        if (!phoneRaw || status) continue; // skip empty or already-processed rows

        try {
          const phone = normalizePhone(phoneRaw);
          const executionId = triggerCall(phone);

          sheet.getRange(i + 1, COL.PHONE + 1).setValue(phone);
          sheet.getRange(i + 1, COL.EXEC_ID + 1).setValue(executionId);
          sheet.getRange(i + 1, COL.STATUS + 1).setValue('queued');
        } catch (err) {
          sheet.getRange(i + 1, COL.STATUS + 1).setValue('failed');
          sheet.getRange(i + 1, COL.ERROR + 1).setValue(err.message);
        }
      }
    }
    ```

    <Note>
      This is the **only function you run manually**. All other updates happen automatically through webhooks.
    </Note>
  </Accordion>
</AccordionGroup>

***

## Step 5: Handle Webhook Updates

As each call progresses, Bolna sends POST requests to your webhook URL with status updates. The `doPost` function catches these, matches them to the right row using the `execution_id`, and writes the data back to the sheet:

```javascript theme={"system"}
function doPost(e) {
  let webhook;
  try {
    webhook = JSON.parse(e.postData.contents);
  } catch {
    return ContentService.createTextOutput('Invalid JSON');
  }

  const executionId = webhook.execution_id || webhook.id;
  if (!executionId) return ContentService.createTextOutput('No execution_id');

  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(SHEET_NAME);
  const rows = sheet.getDataRange().getValues();

  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][COL.EXEC_ID]) !== String(executionId)) continue;

    const row = i + 1;

    if (webhook.status)
      sheet.getRange(row, COL.STATUS + 1).setValue(webhook.status);

    if (webhook.updated_at || webhook.created_at)
      sheet.getRange(row, COL.TIMESTAMP + 1).setValue(webhook.updated_at || webhook.created_at);

    if (webhook.status === 'completed') {
      if (webhook.conversation_duration)
        sheet.getRange(row, COL.DURATION + 1).setValue(webhook.conversation_duration + 's');
      if (webhook.transcript)
        sheet.getRange(row, COL.TRANSCRIPT + 1).setValue(webhook.transcript.slice(0, 5000));
    }

    if (webhook.status === 'failed')
      sheet.getRange(row, COL.ERROR + 1).setValue(webhook.error_message || webhook.status);

    break;
  }

  return ContentService.createTextOutput('OK');
}
```

<Note>
  `doPost` is a **reserved function** in Google Apps Script. It runs automatically whenever your deployed script receives an HTTP POST request, so you never invoke it manually. The webhook payload mirrors the [Get Execution API](/docs/api-reference/executions/get_execution) response.
</Note>

***

## Step 6: Deploy and Connect the Webhook

<Steps>
  <Step title="Deploy as a Web App">
    In the Apps Script editor, click **Deploy → New Deployment**. Set the type to **Web App**, execute as **Me**, and grant access to **Anyone**.
  </Step>

  <Step title="Copy the Web App URL">
    After deploying, copy the generated URL. This is your webhook endpoint.
  </Step>

  <Step title="Paste the URL in Bolna">
    In the Bolna dashboard, navigate to your agent's [Extractions tab](/docs/agent-setup/analytics-tab) and paste the URL into the **Webhook URL** field. Bolna will now push call events to this endpoint.
  </Step>
</Steps>

<Warning>
  Every time you edit your Apps Script code, you need to create a **new deployment** for changes to take effect. The live URL changes with each deployment.
</Warning>

***

## Step 7: Run the Automation

<Steps>
  <Step title="Add phone numbers">
    Populate column A in your sheet with the numbers you want to call. Leave columns B through G empty.
  </Step>

  <Step title="Execute the script">
    In the Apps Script editor, select `runBolnaCalls` from the function dropdown and click **Run**.
  </Step>

  <Step title="Watch the data flow">
    Switch to your Google Sheet. You will see execution IDs and `queued` statuses appear immediately. As calls complete, the sheet updates in real time with status, duration, transcripts, and timestamps.
  </Step>
</Steps>

***

## Optional: Add a Run Button to Your Sheet

Create a new file called `ui.gs` in Apps Script and paste the following. After saving, refresh your Google Sheet. A **Bolna** menu will appear in the menu bar.

```javascript theme={"system"}
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Bolna')
    .addItem('Run Calls', 'runBolnaCalls')
    .addToUi();
}
```

***

## How It All Works Together

Here is a quick walkthrough of the entire flow from start to finish:

1. **You fill phone numbers** into Column A of your Google Sheet
2. **`runBolnaCalls()` reads each row**, normalizes the phone number, and sends a POST request to the Bolna [Make a Call API](/docs/api-reference/calls/make)
3. **Bolna returns an `execution_id`** for each call, which the script writes into Column B along with a `queued` status
4. **The Bolna Voice AI Agent** places the call, handles the conversation, and tracks progress internally
5. **On every status change**, Bolna sends a webhook POST to your deployed Apps Script URL
6. **`doPost()` receives the webhook**, finds the matching row by `execution_id`, and fills in the status, duration, transcript, and timestamp
7. **Your Google Sheet stays up to date** automatically as each call completes or fails

<Tip>
  The `execution_id` is what ties everything together. It is returned when a call is triggered and included in every webhook update, so the script always knows exactly which row to update.
</Tip>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Batch Calling" icon="layer-group" href="/docs/guides/outbound/batch-calling">
    Run large-scale campaigns with built-in concurrency controls
  </Card>

  <Card title="Data Extractions" icon="filter" href="/docs/guides/prompting/using-extractions">
    Pull structured fields like intent, sentiment, or confirmed appointments from calls
  </Card>

  <Card title="Auto Retry" icon="rotate" href="/docs/guides/outbound/auto-retry">
    Automatically re-attempt unanswered or failed calls
  </Card>

  <Card title="Webhooks Reference" icon="webhook" href="/docs/guides/post-call/polling-call-status-webhooks">
    Full reference for webhook payloads and call status polling
  </Card>
</CardGroup>
