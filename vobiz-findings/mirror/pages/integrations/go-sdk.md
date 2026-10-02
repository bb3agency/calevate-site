> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Go SDK

> Build Go voice apps with the Vobiz SDK - place outbound calls, manage SIP trunks, and craft VobizXML synchronously for 130+ countries including India.

The official Go SDK for the Vobiz Voice API. Make outbound calls, manage SIP trunks, handle phone numbers, and drive live call flows from idiomatic, type-safe Go.

**Source code:** [vobiz-ai/Vobiz-Go-SDK](https://github.com/vobiz-ai/Vobiz-Go-SDK)

## Installation

Requires Go **1.21** or later. Add the SDK with `go get`:

```bash theme={null}
go get github.com/vobiz-ai/Vobiz-Go-SDK
```

## Quick start

Place an outbound call. When the call connects, Vobiz pings your `AnswerURL` endpoint, and you must respond with a VobizXML payload.

```go theme={null}
package main

import (
    "context"
    "fmt"
    "log"
    "os"

    vobiz "github.com/vobiz-ai/Vobiz-Go-SDK"
    "github.com/vobiz-ai/Vobiz-Go-SDK/client"
    "github.com/vobiz-ai/Vobiz-Go-SDK/option"
)

func main() {
    c := client.NewClient(
        option.WithAPIKey(os.Getenv("VOBIZ_AUTH_ID")),
        option.WithAuthToken(os.Getenv("VOBIZ_AUTH_TOKEN")),
    )

    response, err := c.Calls.MakeCall(context.TODO(), &vobiz.MakeCallRequest{
        AuthID:       os.Getenv("VOBIZ_AUTH_ID"),
        From:         "14155551234",
        To:           "+919876543210",
        AnswerURL:    "https://yourserver.com/answer",
        AnswerMethod: "POST",
    })
    if err != nil {
        log.Fatalf("Error making call: %v", err)
    }

    fmt.Printf("Call queued: %+v\n", response)
}
```

## Authentication

The Go client requires your **Auth ID** and **Auth Token**. Find both in the [Vobiz Console](https://console.vobiz.ai).

Use `option.WithAPIKey` for your Auth ID (mapped to the `X-Auth-ID` header) and `option.WithAuthToken` for your Auth Token (mapped to `X-Auth-Token`):

```go theme={null}
import (
    "github.com/vobiz-ai/Vobiz-Go-SDK/client"
    "github.com/vobiz-ai/Vobiz-Go-SDK/option"
)

c := client.NewClient(
    option.WithAPIKey(os.Getenv("VOBIZ_AUTH_ID")),
    option.WithAuthToken(os.Getenv("VOBIZ_AUTH_TOKEN")),
)
```

## VobizXML

When Vobiz calls your `AnswerURL`, your handler must respond with a VobizXML document that defines the call flow. The SDK ships a typed builder in the `github.com/vobiz-ai/Vobiz-Go-SDK/vobizxml` subpackage - each `Add*` returns the created child for nesting, and `vobizxml.Attr(key, value)` sets attributes in order:

```go theme={null}
import "github.com/vobiz-ai/Vobiz-Go-SDK/vobizxml"

func answerHandler(w http.ResponseWriter, r *http.Request) {
    resp := vobizxml.NewResponse()
    gather := resp.AddGather(
        vobizxml.Attr("action", "https://yourapp.com/menu-choice"),
        vobizxml.Attr("method", "POST"),
        vobizxml.Attr("inputType", "dtmf"),       // Gather uses inputType / executionTimeout
        vobizxml.Attr("numDigits", 1),
        vobizxml.Attr("executionTimeout", 10),
    )
    gather.AddSpeak("Press 1 for sales, 2 for support, or 0 for an operator.")
    resp.AddSpeak("We didn't receive your input. Goodbye.")
    resp.AddHangup()

    w.Header().Set("Content-Type", "application/xml")
    fmt.Fprint(w, resp.String())          // pretty; resp.StringCompact() for one line
}
```

<Note>Prefer the builder, but you can also return a raw VobizXML string if you like. See the [VobizXML reference](/docs/xml/response) for all verbs and attributes.</Note>

## Common operations

### Retrieve account balance

```go theme={null}
balance, err := c.Balance.GetBalance(context.TODO(), &vobiz.GetBalanceRequest{
    AuthID:   os.Getenv("VOBIZ_AUTH_ID"),
    Currency: "USD",
})
if err != nil {
    log.Fatalf("Error retrieving balance: %v", err)
}
fmt.Printf("Balance: %+v\n", balance)
```

### List Call Detail Records (CDRs)

```go theme={null}
response, err := c.Cdr.ListCdrs(context.TODO(), &vobiz.ListCdrsRequest{
    AuthID:  os.Getenv("VOBIZ_AUTH_ID"),
    Page:    vobiz.Int(1),
    PerPage: vobiz.Int(50),
})
if err != nil {
    log.Fatalf("Error listing CDRs: %v", err)
}
fmt.Printf("CDRs: %+v\n", response)
```

### Create a SIP trunk

```go theme={null}
trunk, err := c.Trunks.CreateTrunk(context.TODO(), &vobiz.CreateTrunkRequest{
    AuthID:             os.Getenv("VOBIZ_AUTH_ID"),
    Name:               "My Outbound Trunk",
    TrunkType:          "OUTBOUND",
    MaxConcurrentCalls: 10,
})
if err != nil {
    log.Fatalf("Error creating SIP trunk: %v", err)
}
fmt.Printf("Trunk created: %+v\n", trunk)
```

## Error handling

The SDK returns a standard Go `error` for any non-2xx response. Always check `err` before using the response:

```go theme={null}
response, err := c.Balance.GetBalance(context.TODO(), &vobiz.GetBalanceRequest{
    AuthID:   os.Getenv("VOBIZ_AUTH_ID"),
    Currency: "USD",
})
if err != nil {
    log.Printf("API call failed: %v", err)
    return
}
```

## Resources

* [GitHub repository](https://github.com/vobiz-ai/Vobiz-Go-SDK)
* [Vobiz Console](https://console.vobiz.ai)
* [API documentation](/docs/introduction)
* [VobizXML reference](/docs/xml/response)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.