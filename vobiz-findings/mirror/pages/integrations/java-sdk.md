> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Java SDK

> Build Java voice apps with the Vobiz SDK - outbound calls, SIP trunks, CDR, and call recording across 130+ countries including India.

The official Java SDK for the Vobiz Voice API. Make calls, manage SIP trunks, handle CDR, record calls, configure phone numbers, and more - natively from your Java or JVM backend, with a fully typed builder API.

**Source code:** [vobiz-ai/Vobiz-Java-SDK](https://github.com/vobiz-ai/Vobiz-Java-SDK)

## Installation

The SDK is distributed from its GitHub repo (not Maven Central). Clone it and install it into your local Maven repository, then depend on `ai.vobiz:vobiz-java`:

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Java-SDK.git
cd Vobiz-Java-SDK
gradle publishToMavenLocal
```

```groovy theme={null}
// build.gradle  (add mavenLocal() to repositories)
implementation 'ai.vobiz:vobiz-java:0.0.1'
```

Or include the cloned project as a module / built jar directly.

## Authentication

All API calls require your **Auth ID** and **Auth Token**, available in the [Vobiz Console](https://console.vobiz.ai). Pass your Auth ID to `.apiKey()` and your Auth Token to `.authToken()` - the SDK sends them as the `X-Auth-ID` and `X-Auth-Token` headers.

```java theme={null}
import com.vobiz.api.VobizApiClient;

VobizApiClient client = VobizApiClient
    .builder()
    .apiKey(System.getenv("VOBIZ_AUTH_ID"))
    .authToken(System.getenv("VOBIZ_AUTH_TOKEN"))
    .build();
```

## Quick start

Make an outbound call:

```java theme={null}
import com.vobiz.api.VobizApiClient;
import com.vobiz.api.resources.calls.requests.MakeCallRequest;

public class Example {
    public static void main(String[] args) {
        VobizApiClient client = VobizApiClient
            .builder()
            .apiKey(System.getenv("VOBIZ_AUTH_ID"))
            .authToken(System.getenv("VOBIZ_AUTH_TOKEN"))
            .build();

        client.calls().makeCall(
            "MA_XXXXXX",                       // your account Auth ID
            MakeCallRequest
                .builder()
                .from("14155551234")           // Vobiz-enabled number or SIP URI
                .to("+919876543210")           // destination in E.164 format
                .answerUrl("https://example.com/answer")  // webhook returning VobizXML
                .answerMethod("POST")
                .build()
        );
        System.out.println("Call initiated successfully!");
    }
}
```

## VobizXML

When a call is answered, Vobiz fetches **VobizXML** from your `answerUrl` webhook to control the call. The SDK ships a typed builder in the `com.vobiz.api.vobizxml` package so you can construct documents fluently instead of concatenating strings - each `add*` method returns the created child for nesting, and `.attr(...)` sets attributes in order:

```java theme={null}
import com.vobiz.api.vobizxml.ResponseElement;
import com.vobiz.api.vobizxml.GatherElement;

ResponseElement response = new ResponseElement();

GatherElement gather = response.addGather()
    .attr("action", "https://yourapp.com/menu-choice")
    .attr("method", "POST")
    .attr("inputType", "dtmf")     // camelCase attribute names map straight to VobizXML
    .attr("numDigits", 1)
    .attr("executionTimeout", 10); // Gather uses executionTimeout, never timeout
gather.addSpeak("Press 1 for sales, 2 for support, or 0 for an operator.");

response.addSpeak("We didn't receive your input. Goodbye.");
response.addHangup();

String xml = response.toString();      // pretty-printed, with the XML declaration
String compact = response.toXml(false); // single line - return this from your webhook
```

This produces:

```xml theme={null}
<Response>
    <Gather action="https://yourapp.com/menu-choice" method="POST" inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak>Press 1 for sales, 2 for support, or 0 for an operator.</Speak>
    </Gather>
    <Speak>We didn't receive your input. Goodbye.</Speak>
    <Hangup/>
</Response>
```

Return the serialized string from your webhook handler with `Content-Type: application/xml`. The builder covers all VobizXML verbs - `addSpeak`, `addPlay`, `addWait`, `addGather` (plus `addGetDigits` / `addGetInput` aliases), `addDial` (with `addNumber` / `addUser` / `addRecord`), `addRecord`, `addConference`, `addDtmf`, `addRedirect`, `addHangup`, `addPreAnswer`, and `addStream` - and handles XML escaping, booleans (`true`/`false`), and raw SSML passthrough via `addSpeak().ssml("...")`.

## Resources

* [GitHub repository](https://github.com/vobiz-ai/Vobiz-Java-SDK)
* [Vobiz Console](https://console.vobiz.ai)
* [API documentation](/docs/introduction)
* [VobizXML reference](/docs/xml/response)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.