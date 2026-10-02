> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# C# / .NET SDK

> Build C# and .NET 8 voice apps with the Vobiz SDK - outbound calls, SIP trunks, and VobizXML with native DI for global calling in 130+ countries.

The official C# SDK for the Vobiz Voice API. Make outbound calls, manage SIP trunks, handle phone numbers, and drive live call flows natively within .NET Core / .NET 8 applications.

**Source code:** [vobiz-ai/Vobiz-Csharp-sdk](https://github.com/vobiz-ai/Vobiz-Csharp-sdk)

## Installation

The SDK is distributed from its GitHub repo (not NuGet). Clone it and add a project reference:

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Csharp-sdk.git
dotnet add reference ./Vobiz-Csharp-sdk/src/Vobiz/Vobiz.csproj
```

## Quick start

Place an outbound call with `MakeCallAsync`. When the recipient answers, Vobiz fetches your `AnswerUrl`, which must return a VobizXML document.

```csharp theme={null}
using Vobiz;
using System;
using System.Threading.Tasks;

string authToken = Environment.GetEnvironmentVariable("VOBIZ_AUTH_TOKEN") ?? "YOUR_AUTH_TOKEN";
string authId = Environment.GetEnvironmentVariable("VOBIZ_AUTH_ID") ?? "YOUR_AUTH_ID";

// Constructor order is (authToken, authId)
var client = new VobizApiClient(authToken, authId);

var response = await client.Calls.MakeCallAsync(
    new MakeCallRequest
    {
        AuthId = authId,
        From = "14155551234",
        To = "+919876543210",
        AnswerUrl = "https://yourserver.com/answer",
        AnswerMethod = "POST",
    }
);

Console.WriteLine($"Call UUID: {response.CallUuid}");
```

## Authentication

The .NET SDK uses your **Auth Token** and **Auth ID**. Find both in the [Vobiz Console](https://console.vobiz.ai). The SDK sets the `X-Auth-Token` and `X-Auth-ID` headers on every request.

Pass the Auth Token first, then the Auth ID, to the `VobizApiClient` constructor. Load credentials from environment variables rather than hardcoding them:

```csharp theme={null}
using Vobiz;
using System;

string authToken = Environment.GetEnvironmentVariable("VOBIZ_AUTH_TOKEN") ?? "YOUR_AUTH_TOKEN";
string authId = Environment.GetEnvironmentVariable("VOBIZ_AUTH_ID") ?? "YOUR_AUTH_ID";

var client = new VobizApiClient(authToken, authId);
```

All network-bound methods are asynchronous and return a `Task` or `Task<T>`; use them with `async`/`await`.

## VobizXML

When Vobiz calls your `AnswerUrl`, your controller must respond with a VobizXML document that defines the call flow. The SDK ships a typed builder in the `Vobiz.Xml` namespace - each `Add*` returns the created child for nesting, and `Attrs` keeps attribute order:

```csharp theme={null}
using Vobiz.Xml;

[HttpPost("/answer")]
public ContentResult Answer()
{
    var response = new ResponseElement();
    var gather = response.AddGather(new Attrs
    {
        { "action", "https://yourapp.com/menu-choice" },
        { "method", "POST" },
        { "inputType", "dtmf" },          // Gather uses inputType / executionTimeout
        { "numDigits", 1 },
        { "executionTimeout", 10 },
    });
    gather.AddSpeak("Press 1 for sales, 2 for support, or 0 for an operator.");
    response.AddSpeak("We didn't receive your input. Goodbye.");
    response.AddHangup();

    return Content(response.ToString(), "application/xml");  // ToString(false) for one line
}
```

<Note>Prefer the builder, but returning a raw VobizXML string also works. See the [VobizXML reference](/docs/xml/response) for all verbs and attributes.</Note>

## Common operations

### Convert text to speech on a live call

```csharp theme={null}
await client.SpeakText.CallAsync(
    new SpeakTextCallRequest
    {
        AuthId = authId,
        CallUuid = "call_uuid_here",
        Text = "Hello, your appointment is confirmed for tomorrow at 3 PM.",
        Voice = "WOMAN",
        Language = "en-US",
    }
);
```

### Create a SIP trunk

```csharp theme={null}
var trunk = await client.Trunks.CreateTrunkAsync(
    new CreateTrunkRequest
    {
        AuthId = authId,
        Name = "My Outbound Trunk",
        TrunkType = "OUTBOUND",
        MaxConcurrentCalls = 10,
    }
);

Console.WriteLine($"Trunk created with ID: {trunk.TrunkId}");
```

### List call recordings

```csharp theme={null}
var recordings = await client.Recordings.ListRecordingsAsync(
    new ListRecordingsRequest { AuthId = authId }
);

foreach (var recording in recordings.Recordings)
{
    Console.WriteLine($"Recording ID: {recording.RecordingId}");
}
```

### Send DTMF tones

```csharp theme={null}
await client.Dtmf.SendDtmfAsync(
    new SendDtmfRequest
    {
        AuthId = authId,
        CallUuid = "call_uuid_here",
        Digits = "1234",
        Leg = SendDtmfRequestLeg.Aleg,
    }
);
```

## Error handling

The SDK throws a standard `Exception` on network errors or non-success HTTP status codes. Wrap calls in a `try/catch`:

```csharp theme={null}
try
{
    await client.LiveCalls.HangupCallAsync(
        new HangupCallRequest { AuthId = authId, CallUuid = "invalid_uuid" }
    );
}
catch (Exception ex)
{
    Console.WriteLine($"API request failed: {ex.Message}");
}
```

## Resources

* [GitHub repository](https://github.com/vobiz-ai/Vobiz-Csharp-sdk)
* [Vobiz Console](https://console.vobiz.ai)
* [API documentation](/docs/introduction)
* [VobizXML reference](/docs/xml/response)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.