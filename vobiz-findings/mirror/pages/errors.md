> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz API Error Handling – Status Codes & Response Formats

> Every Vobiz API error returns a consistent JSON payload with error codes, HTTP status, and messages - reference this guide to handle auth failures, rate limits, and billing errors in production.

All errors follow a consistent format for easy parsing and debugging.

## Error Response Format

All API errors use a standardized JSON format:

```json Standard Error Response theme={null}
{
  "status": "error",
  "error": {
    "code": "INSUFFICIENT_BALANCE",
    "message": "Account balance too low to complete this operation",
    "details": {
      "required": 1000,
      "available": 450,
      "currency": "USD"
    }
  },
  "timestamp": "2025-10-12T10:30:00.000Z",
  "requestId": "req_7a8b9c0d1e2f"
}
```

### Response Fields

| Field | Description |
| - | - |
| `status` | Always `"error"` for error responses |
| `error.code` | Machine-readable error code (uppercase, underscore-separated) |
| `error.message` | Human-readable error description |
| `error.details` | Additional context (optional, varies by error) |
| `timestamp` | When the error occurred |
| `requestId` | Unique request identifier for support/debugging |

## HTTP Status Codes

### 2xx Success

| Code | Meaning |
| - | - |
| **200 OK** | Request successful, response contains data |
| **201 Created** | Resource created successfully (e.g., trunk, sub-account) |
| **204 No Content** | Request successful, no response body (e.g., DELETE operations) |

### 4xx Client Errors

| Code | Meaning |
| - | - |
| **400 Bad Request** | Invalid request format or parameters |
| **401 Unauthorized** | Missing or invalid authentication credentials |
| **402 Payment Required** | Insufficient account balance |
| **403 Forbidden** | Authenticated but lacking permission for this resource |
| **404 Not Found** | Requested resource does not exist |
| **409 Conflict** | Request conflicts with current state (e.g., duplicate username) |
| **422 Unprocessable Entity** | Validation failed (see details for field errors) |
| **429 Too Many Requests** | Rate limit exceeded |

### 5xx Server Errors

| Code | Meaning |
| - | - |
| **500 Internal Server Error** | Unexpected server error (report via requestId) |
| **502 Bad Gateway** | Downstream service unavailable |
| **503 Service Unavailable** | Service temporarily down or overloaded |
| **504 Gateway Timeout** | Downstream service timeout |

## Common Errors

### Authentication Errors

<AccordionGroup>
  <Accordion title="INVALID_CREDENTIALS - 401">
    Email/password combination incorrect.

    ```json theme={null}
    {
      "status": "error",
      "error": {
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid email or password"
      }
    }
    ```
  </Accordion>

  <Accordion title="TOKEN_EXPIRED - 401">
    Access token has expired (use refresh token).

    ```json theme={null}
    {
      "status": "error",
      "error": {
        "code": "TOKEN_EXPIRED",
        "message": "Access token has expired. Use refresh token to obtain a new one."
      }
    }
    ```
  </Accordion>

  <Accordion title="ACCOUNT_INACTIVE - 403">
    Account has been deactivated.

    ```json theme={null}
    {
      "status": "error",
      "error": {
        "code": "ACCOUNT_INACTIVE",
        "message": "Account is inactive. Contact support to reactivate."
      }
    }
    ```
  </Accordion>
</AccordionGroup>

### Resource Errors

<AccordionGroup>
  <Accordion title="TRUNK_NOT_FOUND - 404">
    Trunk ID does not exist or belongs to a different account.

    ```json theme={null}
    {
      "status": "error",
      "error": {
        "code": "TRUNK_NOT_FOUND",
        "message": "SIP trunk not found",
        "details": { "trunkId": "TRK_invalid123" }
      }
    }
    ```
  </Accordion>

  <Accordion title="DUPLICATE_USERNAME - 409">
    Trunk username already exists.

    ```json theme={null}
    {
      "status": "error",
      "error": {
        "code": "DUPLICATE_USERNAME",
        "message": "Username already exists",
        "details": {
          "username": "mytrunk",
          "suggestion": "Try mytrunk2 or mytrunk_2025"
        }
      }
    }
    ```
  </Accordion>
</AccordionGroup>

### Balance & Billing Errors

<AccordionGroup>
  <Accordion title="INSUFFICIENT_BALANCE - 402">
    Account balance too low.

    ```json theme={null}
    {
      "status": "error",
      "error": {
        "code": "INSUFFICIENT_BALANCE",
        "message": "Insufficient balance to purchase phone number",
        "details": {
          "required": 1000,
          "available": 450,
          "currency": "USD",
          "shortfall": 550
        }
      }
    }
    ```
  </Accordion>

  <Accordion title="PAYMENT_FAILED - 402">
    Payment processing failed.

    ```json theme={null}
    {
      "status": "error",
      "error": {
        "code": "PAYMENT_FAILED",
        "message": "Payment declined by gateway",
        "details": {
          "gateway": "razorpay",
          "reason": "Insufficient funds in linked account"
        }
      }
    }
    ```
  </Accordion>
</AccordionGroup>

### Rate Limiting

<AccordionGroup>
  <Accordion title="RATE_LIMIT_EXCEEDED - 429">
    Too many requests or calls.

    ```json theme={null}
    {
      "status": "error",
      "error": {
        "code": "RATE_LIMIT_EXCEEDED",
        "message": "CPS limit exceeded for this trunk",
        "details": {
          "limitType": "cps",
          "limit": 10,
          "current": 15,
          "retryAfter": 1
        }
      }
    }
    ```
  </Accordion>
</AccordionGroup>

## Validation Errors

When request validation fails (422 status), the response includes detailed field-level errors:

```json Validation Error Response theme={null}
{
  "status": "error",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": {
      "errors": [
        {
          "field": "password",
          "message": "Password must be at least 8 characters",
          "code": "MIN_LENGTH",
          "value": "abc"
        },
        {
          "field": "email",
          "message": "Invalid email format",
          "code": "INVALID_FORMAT",
          "value": "notanemail"
        },
        {
          "field": "maxCps",
          "message": "Must be between 1 and 1000",
          "code": "OUT_OF_RANGE",
          "value": 5000
        }
      ]
    }
  }
}
```

<Info>
  **Handling validation errors:** Parse the `details.errors` array to display field-specific error messages in your UI. Each error includes the field name, error code, and the invalid value.
</Info>

## Troubleshooting Guide

* **Check HTTP status code first** - The status code category tells you who's at fault: 4xx = client error (fix your request), 5xx = server error (retry or contact support).
* **Always log `requestId`** - Save the `requestId` from error responses. When contacting support, include this ID for faster debugging and resolution.
* **Implement exponential backoff** - For 429 (rate limit) and 503 (service unavailable) errors, retry with exponential backoff: wait 1s, then 2s, then 4s, etc. Check the `Retry-After` header if present.
* **Validate before sending** - Implement client-side validation matching API requirements to catch errors before making requests. Reduces unnecessary API calls and improves user experience.
* **Monitor error rates** - Track error response counts and types over time. Sudden spikes in specific error codes may indicate configuration issues or API changes requiring attention.

<Info>
  If you're seeing unexpected errors across multiple requests, check the [Vobiz Status Page](https://status.vobiz.ai) for any active incidents before opening a support ticket.
</Info>

### Common 401 Fixes

* Ensure `X-Auth-ID` and `X-Auth-Token` headers are included
* Check token hasn't expired
* Verify account is active (`is_active=true`)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.