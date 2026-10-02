> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Integration Best Practices – Security, Reliability & Performance

> Secure, reliable, and high-performance Vobiz integrations start here. Covers credential management, webhook hardening, rate limiting, and global compliance patterns.

## Security Best Practices

### Never Hardcode Credentials

Bad practice - credentials baked into source code:

```javascript Hardcoded Credentials (Never Do This) theme={null}
const API_KEY = "sk_live_abc123def456";  // NEVER DO THIS
const PASSWORD = "my_secret_password";    // NEVER DO THIS
```

Good practice - load from environment or a secrets manager:

```javascript Use Environment Variables theme={null}
// Load from environment variables
const API_KEY = process.env.VOBIZ_API_KEY;
const PASSWORD = process.env.VOBIZ_PASSWORD;

// Or use a secrets manager
const secrets = await secretsManager.getSecret("vobiz/credentials");
```

### Use HTTPS for All Requests

<Info>
  Always use `https://` URLs when calling the API. Never send authentication tokens or sensitive data over unencrypted HTTP connections. Our API only responds to HTTPS.
</Info>

### Rotate Credentials Regularly

* Change trunk passwords every 90 days
* Change account passwords regularly and invalidate old refresh tokens
* Immediately rotate if credentials are suspected to be compromised
* Use sub-accounts for different applications/teams to limit blast radius

### Whitelist IP Addresses

For production SIP trunks with static IPs, use IP authentication instead of passwords:

```json IP Whitelist Configuration theme={null}
{
  "authType": "ip",
  "ipWhitelist": [
    "203.0.113.10",  // Production PBX
    "203.0.113.11"   // Backup PBX
  ]
}
```

This eliminates password-based attacks and simplifies configuration for trusted systems.

### Validate Input on Client Side

Implement client-side validation before sending requests to prevent injection attacks:

* Sanitize phone numbers (remove special characters, validate E.164 format)
* Validate email addresses match RFC 5322 spec
* Limit string lengths (trunk names, usernames, etc.)
* Reject suspicious patterns (SQL injection attempts, XSS payloads)

## Authentication & Authorization

### Token Storage

<Warning>
  **Frontend Applications**

  * Store access tokens in memory or sessionStorage (expires when tab closes)
  * Never store tokens in localStorage (vulnerable to XSS attacks)
  * Use httpOnly cookies for refresh tokens if possible
</Warning>

<Tip>
  **Backend Applications**

  * Store tokens in environment variables or secrets manager
  * Encrypt tokens at rest if storing in database
  * Use secure memory storage for short-lived tokens
</Tip>

### Automatic Token Refresh

Implement automatic token refresh before expiration (30 minutes for access tokens):

```javascript Token Refresh Pattern theme={null}
async function makeAuthenticatedRequest(url, options) {
  // Check if token expires in next 5 minutes
  if (tokenExpiresAt - Date.now() < 5 * 60 * 1000) {
    await refreshAccessToken();
  }

  return fetch(url, {
    ...options,
    headers: {
      ...options.headers,
      'Authorization': `Bearer ${access_token}`
    }
  });
}

async function refreshAccessToken() {
  const response = await fetch('https://api.vobiz.ai/api/v1/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refreshToken })
  });

  const data = await response.json();
  accessToken = data.access_token;
  tokenExpiresAt = Date.now() + (30 * 60 * 1000);
}
```

### Use Sub-Accounts for Separation

Create separate sub-accounts for different applications, environments, or teams:

* **Development:** Separate sub-account for testing
* **Production:** Dedicated sub-account with stricter controls
* **Partners:** Sub-accounts for each integration partner
* **Departments:** Sales, Support, Engineering teams get own sub-accounts

## Performance Optimization

### Implement Caching

Cache infrequently changing data to reduce API calls:

| Resource | Cache TTL | Notes |
| - | - | - |
| Account info | 15 minutes | Rarely changes |
| Trunk list | 5 minutes | Invalidate on create/delete |
| Balance | 1 minute | Frequently updated |
| CDRs | No cache | Always fetch fresh |

### Use Pagination Wisely

Don't fetch all records at once. Use pagination for large datasets:

```javascript Efficient Pagination theme={null}
// Fetch CDRs in batches of 100
async function getAllCDRs(auth_id, startDate, endDate) {
  const allCDRs = [];
  let offset = 0;
  const limit = 100;

  while (true) {
    const response = await fetch(
      `https://api.vobiz.ai/api/v1/Account/${auth_id}/cdr?start_date=${startDate}&end_date=${endDate}&limit=${limit}&offset=${offset}`
    );
    const data = await response.json();

    allCDRs.push(...data.data.cdrs);

    if (!data.data.pagination.hasMore) break;
    offset += limit;
  }

  return allCDRs;
}
```

### Batch Operations

Instead of making multiple individual requests, consider implementing client-side batching:

* Batch CDR queries by date ranges instead of querying each day separately
* Combine multiple resource updates in a single transaction when possible
* Use bulk operations for importing/exporting large datasets

### Connection Pooling

Reuse HTTP connections instead of creating new ones for every request:

```javascript Connection Pooling (Node.js) theme={null}
const https = require('https');

// Create agent with connection pooling
const agent = new https.Agent({
  keepAlive: true,
  maxSockets: 50,
  maxFreeSockets: 10,
  timeout: 60000
});

// Reuse agent for all requests
fetch(url, { agent });
```

## Reliability & Error Handling

### Implement Retry Logic

Retry failed requests with exponential backoff for transient errors:

```javascript Retry with Exponential Backoff theme={null}
async function fetchWithRetry(url, options, maxRetries = 3) {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const response = await fetch(url, options);

      // Don't retry 4xx errors (client errors)
      if (response.status >= 400 && response.status < 500) {
return response;
      }

      // Retry 5xx errors and network failures
      if (response.ok) {
return response;
      }

      if (attempt === maxRetries) {
throw new Error(`Failed after ${maxRetries} retries`);
      }

      // Exponential backoff: 1s, 2s, 4s, 8s...
      const delay = Math.pow(2, attempt) * 1000;
      await new Promise(resolve => setTimeout(resolve, delay));

    } catch (error) {
      if (attempt === maxRetries) throw error;

      const delay = Math.pow(2, attempt) * 1000;
      await new Promise(resolve => setTimeout(resolve, delay));
    }
  }
}
```

### Circuit Breaker Pattern

Prevent cascading failures by implementing a circuit breaker:

* Track consecutive failures for each service
* After 5 failures, "open" circuit and fail fast for 30 seconds
* After timeout, allow one request through ("half-open" state)
* If successful, close circuit; if failed, reopen for longer

### Handle Rate Limits Gracefully

When you receive a 429 (Rate Limit) response:

```javascript Handle Rate Limits theme={null}
async function handleRateLimit(response) {
  if (response.status === 429) {
    const retryAfter = response.headers.get('Retry-After') || 60;

    console.log(`Rate limited. Retrying after ${retryAfter} seconds`);

    await new Promise(resolve =>
      setTimeout(resolve, retryAfter * 1000)
    );

    // Retry the request
    return fetch(url, options);
  }

  return response;
}
```

### Retry Billable Writes Carefully

Apply the retry logic above to reads and to writes you can safely repeat. For a write that charges your balance - such as [Purchase from Inventory](/docs/account-phone-number/purchase-from-inventory), which debits the setup fee and monthly fee - read the account state first and skip the retry if the earlier attempt already landed.

[List Account Phone Numbers](/docs/account-phone-number/list-account-phone-numbers) accepts a `search` query parameter that filters by phone number, which makes it a cheap way to confirm ownership before you send the purchase again:

```javascript Confirm Before Retrying a Purchase theme={null}
const authId = process.env.VOBIZ_AUTH_ID;
const headers = {
  'X-Auth-ID': authId,
  'X-Auth-Token': process.env.VOBIZ_AUTH_TOKEN,
  'Content-Type': 'application/json'
};

async function alreadyOnAccount(e164) {
  const res = await fetch(
    `https://api.vobiz.ai/api/v1/Account/${authId}/numbers?search=${encodeURIComponent(e164)}`,
    { headers }
  );
  const body = await res.json();
  return body.items.some(number => number.e164 === e164);
}

async function purchaseOnce(e164) {
  // A timeout or connection reset can still leave the first attempt committed.
  if (await alreadyOnAccount(e164)) return;

  return fetch(
    `https://api.vobiz.ai/api/v1/Account/${authId}/numbers/purchase-from-inventory`,
    { method: 'POST', headers, body: JSON.stringify({ e164 }) }
  );
}
```

Keep the literal `+` in the JSON body, and URL-encode it in the `search` query parameter as shown above.

## Monitoring & Logging

### Log All API Requests

Maintain detailed logs for debugging and auditing:

```javascript Request Logging theme={null}
function logAPIRequest(method, url, status, duration, requestId) {
  console.log({
    timestamp: new Date().toISOString(),
    method,
    url,
    status,
    duration: `${duration}ms`,
    requestId,
    service: 'vobiz-api'
  });
}
```

### Track Key Metrics

<Note>
  * API request success/failure rates
  * Average response times per endpoint
  * Error distribution by error code
  * Token refresh frequency
  * Balance consumption rate
  * Call success rates (ASR)
  * Rate limit violations
</Note>

### Set Up Alerts

Configure alerts for critical events:

* **Balance Low:** Alert when balance drops below threshold
* **Error Spike:** Alert when error rate exceeds 5% of requests
* **Trunk Down:** Alert when trunk authentication fails repeatedly
* **Rate Limit Hit:** Alert when approaching rate limits

## Testing Strategies

### Use Separate Accounts for Testing

Create dedicated test accounts/sub-accounts with separate credentials. Never test in production with real customer data or active trunks.

### Test Error Scenarios

Don't just test happy paths. Verify your application handles errors correctly: invalid credentials, insufficient balance, rate limits, network timeouts, etc.

### Automate Integration Tests

Integrate automated API tests into your CI/CD pipeline to catch regressions early. Run tests on every commit to the main branch to ensure reliability.

### Monitor Test Call Quality

Make regular test calls and verify:

* Call connects within 3 seconds (low PDD)
* Audio quality is clear (no packet loss)
* CDR is generated correctly
* Balance is debited accurately

### Load Testing

Before going live, test with realistic load:

* Simulate expected CPS (calls per second)
* Test concurrent call limits
* Verify rate limiting behaves as expected
* Monitor API response times under load

## Related Guides

<CardGroup cols={2}>
  <Card title="Number Utilization" icon="phone" href="/docs/best-practices/number-utilization">
    Improve connectivity, reduce spam flagging, and stay compliant.
  </Card>

  <Card title="DLT Registration" icon="shield-check" href="/docs/best-practices/dlt-registration">
    Step-by-step DLT registration - Principal Entity, header, and template approval.
  </Card>

  <Card title="140 & 160 Acquisition" icon="hashtag" href="/docs/best-practices/140-160-acquisition">
    Process, documents, and scenarios for 140/160 numbers.
  </Card>

  <Card title="Error Handling" icon="triangle-exclamation" href="/docs/errors">
    Understand error codes and handle them gracefully.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.