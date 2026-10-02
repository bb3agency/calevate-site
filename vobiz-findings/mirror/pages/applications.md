> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Applications API – Configure Answer, Hangup & Message URLs

> Bundle Answer URL, Hangup URL, and Message webhook URLs into reusable Vobiz Applications that control inbound call routing and XML flow for any phone number across 130+ countries.

## Key Concepts

* **Answer URL** - Vobiz requests this URL for a valid Vobiz XML element on an incoming call. The XML returned by this URL determines the flow of the call.
* **Hangup URL** - Vobiz makes an HTTP request to this URL when the call is hung up. Useful for call analytics and cleanup operations.
* **Message URL** - Vobiz sends all incoming messages to this URL. Vobiz expects an HTTP 200 response from this URL.
* **SIP URI** - Every Vobiz application can be called directly without being attached to a number or endpoint. When an incoming call arrives on this URI, Vobiz follows the same flow as it does for a number or endpoint.

## Application Operations

* [The Application Object](/docs/applications/application-object) - View the structure and attributes of the Application object including URLs, methods, and default settings.
* [Create an Application](/docs/applications/create-application) - POST request to create a new application with answer URL, hangup URL, and message URL configuration.
* [Retrieve an Application](/docs/applications/retrieve-application) - GET request to retrieve all details of a specific application by app\_id.
* [Update an Application](/docs/applications/update-application) - POST request to modify application settings. Unspecified parameters remain unchanged.
* [Delete an Application](/docs/applications/delete-application) - DELETE request to permanently remove an application. Optionally cascade delete associated endpoints.
* [List All Applications](/docs/applications/list-all-applications) - GET request to retrieve all applications with optional filtering and pagination support.
* [Attach Number](/docs/applications/attach-number) - Link a phone number to a voice application so incoming calls route to it.
* [Detach Number](/docs/applications/detach-number) - Unlink a phone number from its voice application.

## Webhook Callbacks

### Answer URL Callback

When a call is answered, Vobiz makes a request to your `answer_url` with call details.

**Request Parameters:**

```http theme={null}
POST https://example.com/answer
Content-Type: application/x-www-form-urlencoded

CallUUID=abc123&From=14155551234&To=14155556789&Direction=inbound&CallStatus=ringing
```

**Expected Response (XML):**

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Speak>Welcome to our service</Speak>
  <Gather numDigits="1" action="https://example.com/gather">
    <Speak>Press 1 for sales, 2 for support</Speak>
  </Gather>
</Response>
```

### Hangup URL Callback

When a call ends, Vobiz notifies your `hangup_url` with call details and duration.

**Request Parameters:**

```http theme={null}
POST https://example.com/hangup
Content-Type: application/x-www-form-urlencoded

CallUUID=abc123&CallStatus=completed&Duration=45&HangupCause=NORMAL_CLEARING
```

## Best Practices

<Tip>
  * **Always Use HTTPS:** All webhook URLs (answer\_url, hangup\_url, etc.) must use HTTPS for security.
  * **Handle Retries:** Vobiz retries failed webhook calls up to 3 times. Ensure idempotent operations.
  * **Respond Quickly:** Answer URL must respond within 10 seconds to avoid call timeout.
  * **Validate Webhooks:** Verify requests are from Vobiz using signature validation.
  * **Use Fallback URLs:** Always configure fallback\_answer\_url for production apps to handle failures.
  * **Test in Development:** Use a test account before deploying to a production environment.
  * **Monitor Usage:** Check which numbers/endpoints use each app before deletion.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.