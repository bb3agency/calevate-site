> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Set Up Inbound Calls & Caller Matching

> Configure inbound call settings for Bolna Voice AI. Match callers using CSV, Google Sheets, or API. Set up spam prevention and preload customer data.

## What is the Inbound Tab?

The Inbound Tab is where you configure settings for receiving incoming calls. Match callers to your database, preload user data before the call starts, and set up spam prevention to protect your agents from abuse.

<Frame caption="Inbound Tab on Bolna Playground">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/inbound-tab.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=467a4c70e9d2d725f2da61fe97893735" alt="Inbound Tab showing database matching, call restrictions, and spam prevention settings" width="1024" height="690" data-path="images/getting-started/agent-setup/inbound-tab.png" />
</Frame>

***

## Database for Inbound Phone Numbers

Match incoming calls to users and preload their data before the call starts. Choose from three data source options:

<Tabs>
  <Tab title="Internal APIs">
    Connect your own API to fetch user data dynamically when a call comes in.

    <Frame caption="Use Internal APIs">
      <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/inbound-api.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=7ba88fe9c9378ac65d0dee35c0cefb14" alt="Inbound settings with internal API option showing API Endpoint URL and Auth Token fields" width="1024" height="690" data-path="images/getting-started/agent-setup/inbound-api.png" />
    </Frame>

    <Steps>
      <Step title="Select Data Source">
        Choose **"Use your internal APIs"** from the dropdown.
      </Step>

      <Step title="Enter API Endpoint URL">
        Provide your API endpoint that will receive the caller data request.
      </Step>

      <Step title="Add Auth Token">
        Enter your Bearer token for secure authentication.
      </Step>
    </Steps>

    ### Query Parameters

    Bolna automatically passes these parameters to your API:

    | Parameter        | Description                     |
    | ---------------- | ------------------------------- |
    | `contact_number` | The caller's phone number       |
    | `agent_id`       | Your agent's identifier         |
    | `execution_id`   | Unique identifier for this call |

    <Warning>
      **Your API must return a JSON response** with user details. Bolna will inject this data directly into your agent's prompt for personalized conversations.
    </Warning>

    ### Example API Request

    ```bash theme={"system"}
    curl -X GET "https://your-api.com/user-data?contact_number=+919876543210&agent_id=abc123&execution_id=xyz789" \
      -H "Authorization: Bearer YOUR_AUTH_TOKEN" \
      -H "Content-Type: application/json"
    ```

    ### Example API Response

    ```json theme={"system"}
    {
      "user_name": "John Doe",
      "account_status": "premium",
      "last_purchase": "2026-01-15"
    }
    ```

    <Note>
      Authentication uses Bearer token and is stored securely by Bolna.
    </Note>
  </Tab>

  <Tab title="CSV Upload">
    Upload a CSV file containing your user database.

    <Frame caption="Use CSV File">
      <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/inbound-csv.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=6a1518414225f0dd8adc964ebd70f89c" alt="Inbound settings with CSV option showing Upload CSV File button" width="1024" height="635" data-path="images/getting-started/agent-setup/inbound-csv.png" />
    </Frame>

    <Steps>
      <Step title="Select Data Source">
        Choose **"Use a CSV"** from the dropdown.
      </Step>

      <Step title="Upload CSV File">
        Click **Upload CSV File** and select your file.
      </Step>
    </Steps>

    <Warning>
      The CSV file **must include a `contact_number` column** containing phone numbers. These numbers will be matched against the caller's phone number.
    </Warning>

    ### CSV Format Example

    ```csv theme={"system"}
    contact_number,user_name,account_type
    +919876543210,John Doe,premium
    +918765432109,Jane Smith,basic
    ```
  </Tab>

  <Tab title="Google Sheet">
    Connect a public Google Sheet as your user database.

    <Frame caption="Use Google Sheet">
      <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/inbound-google-sheet.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=2cf3a76b34f6b2d150a34d747e5657e3" alt="Inbound settings with Google Sheet option showing URL and Sheet Name fields" width="1024" height="661" data-path="images/getting-started/agent-setup/inbound-google-sheet.png" />
    </Frame>

    <Steps>
      <Step title="Select Data Source">
        Choose **"Use a public Google Sheet"** from the dropdown.
      </Step>

      <Step title="Enter Google Sheet URL">
        Paste the URL of your public Google Sheet.
      </Step>

      <Step title="Enter Sheet Name">
        Specify the exact name of the sheet tab to use.
      </Step>
    </Steps>

    <Warning>
      The sheet **must be public** and should include a `contact_number` column containing phone numbers.
    </Warning>
  </Tab>
</Tabs>

***

## Call Restrictions

<Info>
  Toggle on **"Allow Calls Only from Database"** to restrict incoming calls to only phone numbers found in your chosen database. Unknown callers will be rejected.
</Info>

***

## Spam Prevention Settings

Protect your agent from spam and abuse.

| Setting                            | Description                                                  |
| ---------------------------------- | ------------------------------------------------------------ |
| **Maximum Calls per Phone Number** | Limit calls from a single number. Set to `-1` for unlimited. |
| **Always-Allow List**              | Phone numbers that bypass all call limits.                   |

<Tip>
  Add your support team and VIP customers to the Always-Allow List to ensure they're never blocked.
</Tip>

***

## Use Cases

<CardGroup cols={2}>
  <Card title="Customer Verification" icon="user-check">
    Only allow calls from registered customers
  </Card>

  <Card title="VIP Support" icon="crown">
    Preload customer data for personalized service
  </Card>

  <Card title="Abuse Prevention" icon="shield">
    Limit repeated calls from the same number
  </Card>

  <Card title="Dynamic Data Loading" icon="database">
    Fetch real-time customer data via API
  </Card>
</CardGroup>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Agent Tab" icon="file-lines" href="/docs/agent-setup/agent-tab">
    Configure prompts and welcome message
  </Card>

  <Card title="Call Tab" icon="phone" href="/docs/agent-setup/call-tab">
    Set up telephony and call management
  </Card>

  <Card title="Receiving Calls Guide" icon="phone-arrow-down" href="/docs/guides/inbound/receiving-incoming-calls">
    Complete inbound setup guide
  </Card>

  <Card title="Phone Numbers" icon="phone-plus" href="/docs/guides/inbound/buying-phone-numbers">
    Purchase and manage phone numbers
  </Card>
</CardGroup>
