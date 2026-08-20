> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Dynamically identify incoming callers

> Use Bolna Voice AI agents to identify callers in real time via API, CSV, or Google Sheets and personalize calls with automatic user data injection.

## What is Caller Identification?

Link your inbound phone numbers to custom data sources. When a call comes in, your Bolna Voice AI agent automatically identifies the caller, matches their number, and pulls in relevant details like name, address, preferences, past history, or any data you provide.

<Frame caption="Bolna Voice AI dynamically identifying and matching incoming callers">
  <img src="https://mintcdn.com/bolna-54a2d4fe/mJ1zPF3eB4Dyupzj/images/identify_incoming_callers.png?fit=max&auto=format&n=mJ1zPF3eB4Dyupzj&q=85&s=4221dd9c003cc476ef050eae23581248" alt="Incoming caller identification interface in Bolna Voice AI showing dynamic data source integration for personalized call handling" width="889" height="567" data-path="images/identify_incoming_callers.png" />
</Frame>

This data is seamlessly injected into the agent's prompt, making every interaction personalized and contextual.

***

## Data Source Options

<Tabs>
  <Tab title="Internal API">
    **Best for:** Teams with existing databases or CRM systems.

    Provide an API endpoint that accepts the caller's phone number. Bolna automatically sends the following parameters:

    | Parameter        | Description                     |
    | ---------------- | ------------------------------- |
    | `contact_number` | Incoming caller's phone number  |
    | `agent_id`       | Agent handling the call         |
    | `execution_id`   | Unique identifier for this call |

    <Frame caption="API integration for real-time caller identification">
      <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/identify_incoming_callers_api.png?fit=max&auto=format&n=DqJpudnR0YtgOS49&q=85&s=88fd129e7dedf4869287bd458346b0a3" alt="API integration setup for real-time caller identification showing endpoint configuration" width="889" height="471" data-path="images/identify_incoming_callers_api.png" />
    </Frame>

    **Example request:**

    ```
    GET https://api.your-domain.com/api/customers?contact_number=+19876543210&agent_id=06f64cb2-...&execution_id=c4be1d0b-...
    ```

    The returned JSON data is automatically merged into the AI prompt before the call begins.

    <Info>
      * The endpoint must be a **GET** endpoint
      * Supported authentication: **Bearer Token**
    </Info>
  </Tab>

  <Tab title="CSV Upload">
    **Best for:** Smaller teams who prefer simple, no-code data management.

    Upload a CSV file with `contact_number` column (phone numbers with country code) and associated user info. Bolna automatically looks up the incoming number and injects matching row data into the prompt.

    <Frame caption="CSV-based caller identification">
      <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/identify_incoming_callers_csv.png?fit=max&auto=format&n=DqJpudnR0YtgOS49&q=85&s=09383b81fca49daddd61ee7612efdf89" alt="CSV file upload interface for caller identification in Bolna Voice AI" width="889" height="459" data-path="images/identify_incoming_callers_csv.png" />
    </Frame>

    ```csv theme={"system"}
    contact_number,first_name,last_name
    +11231237890,Bruce,Wayne
    +91012345678,Bruce,Lee
    +00021000000,Satoshi,Nakamoto
    +44999999007,James,Bond
    ```
  </Tab>

  <Tab title="Google Sheets">
    **Best for:** Real-time sync with spreadsheet simplicity.

    Link a **publicly accessible** Google Sheet with user data. Bolna auto-syncs and looks up the incoming number to pull the latest data. No re-uploads needed.

    <Frame caption="Google Sheets integration for real-time caller recognition">
      <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/identify_incoming_callers_google_sheet.png?fit=max&auto=format&n=DqJpudnR0YtgOS49&q=85&s=88298a89b1ed5e94a3cb76b8916113d1" alt="Google Sheets integration for real-time caller data synchronization in Bolna Voice AI" width="889" height="452" data-path="images/identify_incoming_callers_google_sheet.png" />
    </Frame>

    | contact\_number | first\_name | last\_name |
    | --------------- | ----------- | ---------- |
    | +11231237890    | Bruce       | Wayne      |
    | +91012345678    | Bruce       | Lee        |
    | +00021000000    | Satoshi     | Nakamoto   |
    | +44999999007    | James       | Bond       |

    <Tip>
      Your Google Sheet can be updated at any time. Bolna agents automatically pick up the latest data in real time.
    </Tip>
  </Tab>
</Tabs>

***

## Related Features

<CardGroup cols={3}>
  <Card title="Inbound Call Setup" icon="phone-volume" href="/docs/guides/inbound/receiving-incoming-calls">
    Configure inbound calling for your agents
  </Card>

  <Card title="Using Context" icon="brackets-curly" href="/docs/guides/prompting/using-context">
    Pass dynamic data to personalize conversations
  </Card>

  <Card title="IVR Setup" icon="phone-intercom" href="/docs/guides/inbound/ivr-inbound-calls">
    Route inbound calls with IVR menus
  </Card>
</CardGroup>
