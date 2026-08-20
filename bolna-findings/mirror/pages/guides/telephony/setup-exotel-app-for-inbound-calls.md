> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Setup Exotel with Bolna for Inbound Calling

> Create, setup and configure Exotel Application with your account for enabling Inbound calls with Bolna Voice AI Platform

## How to Create an Exotel App for Inbound Calls

To enable inbound calling functionality with Bolna's Voice AI agents through Exotel, you'll need to create and configure a dedicated app in your Exotel dashboard. This app serves as the communication bridge between Bolna's AI voice agents and Exotel's telephony infrastructure for making incoming calls.

### Understanding Exotel Apps for Voice AI Integration

An Exotel app is a customizable workflow that defines how your inbound calls are handled, routed, and connected. For Bolna integration, you'll configure a specialized app that connects the Voicebot functionality with Bolna's API endpoints, enabling seamless AI-powered inbound calling capabilities.

### Prerequisites for Creating Your Exotel Inbound App

Before you begin, ensure you have:

* An active Exotel account with API access
* Access to your Exotel dashboard at [my.exotel.com](https://my.exotel.com/)

### Step 1: Access the Exotel App Bazaar

Navigate to your [Exotel dashboard](https://my.exotel.com/) and locate the **App Bazaar** section under the **Manage** menu. The App Bazaar is where you'll create and configure custom apps for your telephony workflows.

<Frame caption="Exotel App Bazaar location in dashboard">
  <img src="https://mintcdn.com/bolna-54a2d4fe/HwOYKfzp4mnvdMa0/images/setup_exotel_app_for_inbound_calls_step_1.png?fit=max&auto=format&n=HwOYKfzp4mnvdMa0&q=85&s=518bd1d9e8c1fa97704ead23310a2d50" alt="Exotel dashboard highlighting the App Bazaar menu option under Manage section for creating Bolna Voice AI inbound calling applications" width="3136" height="1568" data-path="images/setup_exotel_app_for_inbound_calls_step_1.png" />
</Frame>

<br />

### Step 2: Create a New App for Bolna Integration

Click the **Create** button to start building your new app. Give it a descriptive name such as **"Bolna Inbound"** (you can customize this name based on your preference for easy reference in your dashboard).

<Frame caption="Creating a new Exotel app for Bolna integration">
  <img src="https://mintcdn.com/bolna-54a2d4fe/HwOYKfzp4mnvdMa0/images/setup_exotel_app_for_inbound_calls_step_2.png?fit=max&auto=format&n=HwOYKfzp4mnvdMa0&q=85&s=3198c136e0e2ce68c7843db1f8d970aa" alt="Exotel app creation interface showing name input field where users configure Bolna AI inbound calling application settings" width="2446" height="1223" data-path="images/setup_exotel_app_for_inbound_calls_step_2.png" />
</Frame>

<br />

### Step 3: Add the Voicebot App Component

Drag the **Voicebot** app from the available components and drop it into the **"Drop app here"** box. This is the primary component that will handle the AI voice interaction.

<Frame caption="Adding Voicebot component to Exotel workflows">
  <img src="https://mintcdn.com/bolna-54a2d4fe/HwOYKfzp4mnvdMa0/images/setup_exotel_app_for_inbound_calls_step_3.png?fit=max&auto=format&n=HwOYKfzp4mnvdMa0&q=85&s=03aba1ae3fd2aeba4190b4f3e61c5bd1" alt="Exotel workflow builder showing Voicebot component being dragged into the app canvas to enable Bolna AI voice agent functionality" width="3136" height="1568" data-path="images/setup_exotel_app_for_inbound_calls_step_3.png" />
</Frame>

<br />

### Step 4: Configure the Voicebot Component

Once dropped, a configuration popup will appear for the Voicebot settings:

* In the URL field, copy and paste the following Bolna API endpoint:

```
https://api.bolna.ai/inbound_call
```

* Enable the **"Record this"** checkbox to record your inbound calls for quality assurance and compliance purposes

<Frame caption="Voicebot configuration panel - Setting up Bolna API endpoint and call recording options for AI voice interactions">
  <img src="https://mintcdn.com/bolna-54a2d4fe/HwOYKfzp4mnvdMa0/images/setup_exotel_app_for_inbound_calls_step_4.png?fit=max&auto=format&n=HwOYKfzp4mnvdMa0&q=85&s=b05a08de1766b9007bedbd33d4dd56d4" alt="Exotel Voicebot settings showing Bolna API callback URL configuration for inbound AI calling setup" width="2541" height="1271" data-path="images/setup_exotel_app_for_inbound_calls_step_4.png" />
</Frame>

<br />

### Step 5: Configure App for Transfer calling

Within the Voicebot popup, you'll notice another **"Drop app here"** section at the bottom. This is where you'll configure the call connection logic.

Drag and drop the **Connect** voice app into this designated area. This component manages the actual phone call connection and routing.

When the Connect app popup opens, you'll need to specify how connection parameters are controlled:

1. Look for the section titled **"How do you want to control your Connect params?"**
2. Select the option: **"Configure parameters dynamically by providing a URL"**
3. In the **Primary URL** field, copy and paste the following Bolna API endpoint:

```
https://api.bolna.ai/exotel_connect_transfer
```

This configuration allows Bolna to dynamically control call parameters while transferring a live call.

<Frame caption="Connect component configuration for call transfers">
  <img src="https://mintcdn.com/bolna-54a2d4fe/HwOYKfzp4mnvdMa0/images/setup_exotel_app_for_inbound_calls_step_5.png?fit=max&auto=format&n=HwOYKfzp4mnvdMa0&q=85&s=9e60bedc906c453c5487877fd85de794" alt="Exotel Connect app settings showing dynamic URL configuration for Bolna call transfer functionality and call routing setup" width="3136" height="1568" data-path="images/setup_exotel_app_for_inbound_calls_step_5.png" />
</Frame>

<br />

### Step 6: Save Your Exotel App Configuration

Click the **Save** button to finalize your app configuration. Your Exotel inbound app is now ready to work with Bolna's Voice AI platform.

<Frame caption="Saving and completing the Bolna Voice AI inbound calling integration setup">
  <img src="https://mintcdn.com/bolna-54a2d4fe/HwOYKfzp4mnvdMa0/images/setup_exotel_app_for_inbound_calls_step_6.png?fit=max&auto=format&n=HwOYKfzp4mnvdMa0&q=85&s=48748a342ad05a0a24426090d966491a" alt="Exotel app configuration complete with Save button highlighted, showing final step of Bolna AI voice agent inbound calling setup" width="3136" height="1568" data-path="images/setup_exotel_app_for_inbound_calls_step_6.png" />
</Frame>

<br />

Click the **Save** button to finalize your app configuration. Your Exotel inbound app is now ready to work with Bolna's Voice AI platform.

<Frame caption="Saving and completing the Bolna Voice AI inbound calling integration setup">
  <img src="https://mintcdn.com/bolna-54a2d4fe/HwOYKfzp4mnvdMa0/images/setup_exotel_app_for_inbound_calls_step_6.png?fit=max&auto=format&n=HwOYKfzp4mnvdMa0&q=85&s=48748a342ad05a0a24426090d966491a" alt="Exotel app configuration complete with Save button highlighted, showing final step of Bolna AI voice agent inbound calling setup" width="3136" height="1568" data-path="images/setup_exotel_app_for_inbound_calls_step_6.png" />
</Frame>

<br />

### Step 7: Connect the Exophone with the created Exotel App

<Frame caption="Connecting the Exophone with the Exotel Inbound App">
  <img src="https://mintcdn.com/bolna-54a2d4fe/Q5__-uunIJquKkYz/images/setup_exotel_app_for_inbound_calls_step_7.png?fit=max&auto=format&n=Q5__-uunIJquKkYz&q=85&s=1edb5f0d2aa35f72061ffa2ef1d5d54e" alt="Exotel inbound app being connected to the Exophone for inbound calls" width="2858" height="754" data-path="images/setup_exotel_app_for_inbound_calls_step_7.png" />
</Frame>

<br />

### Obtaining Your Exotel App ID

After saving your app, Exotel will generate a unique **App ID** for your configuration. This ID is what you'll use when configuring inbound calling campaigns in Bolna. You can find this ID in your Exotel App Bazaar dashboard next to your newly created app.

<Note>
  **Important**: Make sure to test your app configuration with a test call before launching production campaigns to ensure all components are working correctly together.
</Note>
