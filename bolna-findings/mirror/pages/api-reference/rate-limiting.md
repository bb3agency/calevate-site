> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Rate Limiting for Bolna APIs

> Understand the API rate limits applied to Bolna API endpoints to ensure fair usage and platform stability.

All Bolna API endpoints are subject to rate limiting to ensure fair usage and maintain platform stability. Rate limits are applied per **organization** (if the user belongs to one) or per **user** otherwise.

## Rate Limits

### Endpoint-Specific Limits

The following endpoints have specific rate limits:

| Endpoint                                                                            | Rate Limit          |
| ----------------------------------------------------------------------------------- | ------------------- |
| [/v2/agent/{agent_id}/executions](/docs/api-reference/agent/v2/get_all_agent_executions) | 500 requests/minute |
| [/v2/agent/{agent_id}](/docs/api-reference/agent/v2/get)                                 | 500 requests/minute |
| [/call](/docs/api-reference/calls/make)                                                  | 500 requests/minute |

### Default Limit

All other API endpoints are subject to a default rate limit of **1000 requests per minute**.

## How Rate Limits Are Applied

* If your account is part of an **organization**, the rate limit is shared across all users within that organization.
* If your account is **not** part of an organization, the rate limit applies to your individual user account.

## Exceeding the Rate Limit

If you exceed the rate limit for an endpoint, the API will return an **HTTP 429 (Too Many Requests)** response. When this happens:

* Wait before retrying the request.
* Implement exponential backoff in your application to gracefully handle rate limit responses.

## Best Practices

* **Cache responses** where possible to reduce the number of API calls.
* **Use webhooks** instead of polling for call status updates to minimize requests to execution endpoints.
* **Spread requests** evenly over time rather than sending them in bursts.
* **Monitor your usage** and implement client-side rate limiting to stay within the allowed limits.
