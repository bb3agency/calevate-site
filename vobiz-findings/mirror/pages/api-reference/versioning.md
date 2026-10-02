> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz API Versioning & Deprecation Policy

> How Vobiz versions the REST API, which changes are additive versus breaking, and the deprecation lifecycle with Deprecation and Sunset response headers.

The Vobiz REST API is versioned in the URL path. The current version is **v1**, and every request carries it:

```text theme={null}
https://api.vobiz.ai/api/v1
```

The version lives entirely in the path, so an integration pinned to `/api/v1` keeps talking to v1 until you change the URL yourself. Pinning is the only version control you need - the URL you deploy is the contract you get.

## Compatibility contract

Vobiz ships changes to v1 continuously. Anything on the additive list can appear in v1 at any time, without notice, so build your client to tolerate it. Anything on the breaking list goes through the [deprecation lifecycle](#deprecation-lifecycle) instead.

### Additive changes

| Change | Example |
| - | - |
| A new endpoint | A new path added under `/api/v1` |
| A new optional request field | A new optional body property on an existing operation |
| A new response field | A new key in an existing JSON response object |
| A new value in an output-only enum | A new status or hangup-cause string in a response |
| A new optional response header | Diagnostic metadata on an existing response |

### Breaking changes

| Change | Example |
| - | - |
| Removing or renaming a field | Dropping a response key your code reads |
| Changing a field's type | An integer becoming a string |
| Changing the HTTP status code for an outcome | A `200` becoming a `201` |
| Making an optional request field required | A body property gaining a `required` constraint |
| Removing an endpoint | Retiring a path under `/api/v1` |
| Removing a value from a request enum | Rejecting an input value that used to be accepted |

<Info>
  **Ignore unknown response fields.** Parse responses leniently: read the keys you need and skip the ones you do not recognise. Clients that reject unexpected keys - strict schema validators, generated models with "additional properties" turned off, exhaustive `switch` statements over enum values - break on additive changes that are safe by design.
</Info>

## Deprecation lifecycle

A breaking change to v1 moves through four stages.

<Steps>
  <Step title="Announced">
    The change is documented. The affected field or endpoint keeps working exactly as before, and the docs name the replacement.
  </Step>

  <Step title="Deprecated">
    The resource is marked `deprecated` in the [OpenAPI specification](https://vobiz.ai/openapi.json) and, where it applies to a whole endpoint, responses carry a `Deprecation` header. Behaviour is unchanged - the marker is a signal to migrate.
  </Step>

  <Step title="Sunset">
    A removal date is set and published in the `Sunset` header alongside `Deprecation`. The resource still works up to that date.
  </Step>

  <Step title="Removed">
    The field or endpoint is gone. Requests that depend on it fail - see [Error Handling](/docs/errors) for the response shape.
  </Step>
</Steps>

Vobiz keeps a deprecated endpoint available for a minimum of **\[N] months** between the sunset announcement and removal, so you have a defined window to migrate.

## Deprecation and Sunset headers

When an endpoint enters the deprecation lifecycle, Vobiz signals it with two standard HTTP response headers. They use different formats - do not parse them the same way.

```http theme={null}
Deprecation: @1751327999
Sunset: Tue, 30 Jun 2026 23:59:59 GMT
```

| Header | Specification | Format | Meaning |
| - | - | - | - |
| `Deprecation` | [RFC 9745](https://www.rfc-editor.org/rfc/rfc9745.html) | Structured Fields Date: `@` followed by seconds since the Unix epoch | When the endpoint became (or becomes) deprecated |
| `Sunset` | [RFC 8594](https://www.rfc-editor.org/rfc/rfc8594.html) | HTTP-date | When the endpoint is expected to stop responding |

In the example above, `@1751327999` is `Mon, 30 Jun 2025 23:59:59 GMT` and the sunset follows a year later. A `Deprecation` value in the future means the endpoint is scheduled for deprecation and is not deprecated yet.

Treat both headers as advisory metadata: log them, alert on them, and keep processing the response body normally. No v1 endpoint carries a sunset date today.

<Info>
  Every v1 response goes through the same auth path regardless of deprecation state. See [Authentication](/docs/api-reference/authentication) for the required headers.
</Info>

## Currently deprecated

Three request properties on `POST /api/v1/Account/{auth_id}/trunks` are marked `deprecated` in the OpenAPI specification. They still work; new integrations should use the replacements.

| Deprecated property | Use instead |
| - | - |
| `username` | `credential_uuid` |
| `password` | `credential_uuid` |
| `ip_whitelist` | `ipacl_uuid` |

`credential_uuid` attaches an existing SIP credential (username, password, realm) by UUID, and `ipacl_uuid` attaches an existing IP access-control list. Create those resources first, then pass their UUIDs. See [Create a Trunk](/docs/trunks/create-trunk), [SIP credentials](/docs/trunks/credentials/create-credential), and [IP access control lists](/docs/trunks/ip-acl/create-ip-acl).

## Staying current

* Generate your client from the [OpenAPI specification](https://vobiz.ai/openapi.json) and regenerate it periodically - `deprecated: true` markers surface as deprecation warnings in most generators.
* Keep response parsing lenient so additive changes land without a deploy.
* Watch for `Deprecation` and `Sunset` headers in your HTTP client middleware and surface them in your logs.
* Check the [Vobiz status page](https://status.vobiz.ai) for live service availability.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.