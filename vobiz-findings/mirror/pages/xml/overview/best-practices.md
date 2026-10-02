> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz XML Best Practices – Reliable & Scalable Voice Apps

> Proven patterns for robust Vobiz XML apps - fast webhook responses, audio caching, fallback flows, CallUUID logging, and scalable IVR architecture globally.

## Performance Optimization

### Fast Webhook Responses

Return XML within 1–2 seconds. Slow webhooks create dead air and frustrated callers.

<CodeGroup>
  ```javascript Bad: Slow synchronous processing theme={null}
  app.post('/answer', async (req, res) => {
    // DON'T: Heavy processing blocks the response
    await sendEmail(req.body.From);
    await logToDatabase(req.body);
    await fetchCustomerHistory(req.body.From);

    res.send(xml); // Too slow!
  });
  ```

  ```javascript Good: Fast response, async processing theme={null}
  app.post('/answer', (req, res) => {
    // DO: Return XML immediately
    res.send(xml);

    // Process heavy tasks asynchronously
    processCallWebhook(req.body).catch(err => log(err));
  });
  ```
</CodeGroup>

### Cache Frequently Used Data

Cache business hours, routing rules, audio URLs, and other static data. Avoid querying the database on every webhook - use Redis, memcached, or in-memory caching instead.

### Optimize Audio Files

Use 8 kHz mono MP3 files served from a CDN. Higher quality does not improve telephony audio but increases latency and bandwidth costs.

## Reliability & Error Handling

### Always Provide Fallback Paths

Every Gather and Dial element should have a fallback for timeouts or failures.

```xml Good: Fallback after timeout theme={null}
<Response>
    <Gather numDigits="1" executionTimeout="10" action="/menu">
        <Speak>Press 1 for sales, 2 for support.</Speak>
    </Gather>
    <!-- Fallback if no input received -->
    <Speak>We didn't receive your selection. Transferring to operator.</Speak>
    <Dial>+14155550000</Dial>
</Response>
```

### Validate XML Syntax

Use XML validators in development and automated tests. Malformed XML causes call failures.

* Ensure all tags are properly closed
* Escape special characters (`&`, `<`, `>`, `"`, `'`)
* Use UTF-8 encoding declaration
* Test with real XML parsers, not string validation

### Why did my call answer and immediately drop?

**Malformed XML is not returned to you as an HTTP error.** Your endpoint's own
`200 OK` is accepted, the call answers, and then dies roughly one second later.
No webhook explains it - not `Hangup`, not the status callbacks.

The only trace is in the [CDR](/docs/cdr):

```
hangup_source      Error
hangup_cause_name  Invalid Answer XML
HangupCauseCode    8011
```

If you see code **`8011`**, your answer XML did not parse. By far the most common
cause is a bare `&` in a URL carrying two query parameters, which is invalid
inside an XML attribute:

```xml theme={null}
<!-- broken: the bare & ends the document -->
<Dial action="https://example.com/next?id=1&type=warm">

<!-- correct -->
<Dial action="https://example.com/next?id=1&amp;type=warm">
```

Escape `&` as `&amp;` in every attribute value, including inside URLs. Validate
the rendered document with a real XML parser before returning it - a template that
produces valid-looking output is not the same as valid XML.

### Handle Network Failures Gracefully

If Vobiz cannot reach your webhook URL (timeout, DNS failure, SSL error), the call drops. Use monitoring tools, health checks, and load balancers to ensure high availability.

### Log Everything

Log all incoming webhooks, generated XML, and errors. Use `CallUUID` to trace call flows.

```javascript Comprehensive Logging theme={null}
app.post('/answer', (req, res) => {
  const callId = req.body.CallUUID;

  logger.info('Incoming call', {
    callId,
    from: req.body.From,
    to: req.body.To
  });

  const xml = generateXML(req.body);
  logger.info('Returning XML', { callId, xml });

  res.send(xml);
});
```

## Security

### Validate Webhook Signatures

Verify that webhook requests actually come from Vobiz by checking signatures or an IP allowlist. This prevents spoofed requests.

### Use HTTPS

All webhook URLs must use HTTPS. HTTP webhooks expose call data and may be rejected.

### Sanitize User Input

Do not trust DTMF digits, caller IDs, or other webhook data. Validate and sanitize before using them in database queries or business logic.

```javascript Input Validation theme={null}
app.post('/menu', (req, res) => {
  const digit = req.body.Digits;

  // Validate input is a single digit
  if (!/^[0-9]$/.test(digit)) {
    return res.send(errorXML);
  }

  // Safe to use now
  routeToQueue(digit);
});
```

### Protect Sensitive Data

Never speak credit card numbers, passwords, or SSNs in TTS. Do not log PII without encryption. Use secure storage for call recordings that contain sensitive information.

## User Experience

### Keep Prompts Concise

Callers lose attention after 15–20 seconds. Break long messages into shorter chunks.

<CodeGroup>
  ```xml Bad: Too long theme={null}
  <Speak>
      Welcome to ABC Company, provider of enterprise software solutions
      since 1995. We offer 24/7 support, training, consulting, and managed
      services. For sales press 1, for support press 2, for billing press 3...
  </Speak>
  ```

  ```xml Good: Concise and clear theme={null}
  <Speak>
      Welcome to ABC Company. Press 1 for sales, 2 for support, or 0 for operator.
  </Speak>
  ```
</CodeGroup>

### Provide Clear Instructions

Tell callers exactly what to do. "Press pound when done" or "Say yes or no" is clearer than assuming they know what is expected.

### Allow Menu Repetition

Offer a "Press 9 to repeat this menu" option. Callers often miss options the first time.

### Set Appropriate Timeouts

For simple menus, 10 seconds is reasonable. For account numbers or complex input, allow 15–20 seconds. Too short frustrates callers; too long wastes time.

### Confirm Critical Actions

Before processing payments, canceling services, or other important actions, read back the input and ask for confirmation.

```xml Confirmation Pattern theme={null}
<Response>
    <Speak>You entered account number 1-2-3-4-5-6. Press 1 to confirm or 2 to re-enter.</Speak>
    <Gather numDigits="1" action="/confirm"/>
</Response>
```

### Test with Real Users

Have colleagues or beta users call your IVR. You will discover confusing prompts, unclear options, and timing issues that are not obvious during development.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.