> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Python SDK

> Build Python voice apps with the Vobiz SDK - outbound calls, SIP trunking, VobizXML, and Flask webhook handlers for 130+ countries including India.

The official Python SDK for the Vobiz Voice API. Make outbound calls, manage SIP trunks, handle phone numbers, and build dynamic call flows using VobizXML - all seamlessly integrated into your Python applications.

**Source code and reference:** [vobiz-ai/Vobiz-Python-SDK](https://github.com/vobiz-ai/Vobiz-Python-SDK)

## Installation

The SDK is distributed from its GitHub repo (not a package registry). Clone it and install from source:

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Python-SDK.git
pip install ./Vobiz-Python-SDK
```

## Quick start

Make an outbound call:

```python theme={null}
from vobiz import Vobiz

AUTH_ID = "YOUR_AUTH_ID"

client = Vobiz(api_key=AUTH_ID, auth_token="YOUR_AUTH_TOKEN")

response = client.calls.make_call(
    auth_id=AUTH_ID,
    from_="14155551234",                            # your Vobiz DID number or SIP URI
    to="+919876543210",                             # destination number
    answer_url="https://your-server.com/answer",    # server returning VobizXML
    answer_method="POST",
)

print("Call initiated:", response)
```

When the destination party answers, Vobiz makes a synchronous HTTP request to your `answer_url` to ask for instructions on what to do next.

## Authentication

Vobiz uses your **Auth ID** and **Auth Token**. Find both in the [Vobiz Console](https://console.vobiz.ai).

The `Vobiz` client takes them directly - `api_key` maps to your Auth ID and `auth_token` to your Auth Token:

```python theme={null}
from vobiz import Vobiz

client = Vobiz(api_key="MA_XXXXXXXXXX", auth_token="your_token")
```

We recommend keeping credentials out of source by reading them from environment variables:

```bash theme={null}
export VOBIZ_AUTH_ID=MA_XXXXXXXXXX
export VOBIZ_AUTH_TOKEN=your_token_here
```

```python theme={null}
import os
from vobiz import Vobiz

client = Vobiz(
    api_key=os.environ["VOBIZ_AUTH_ID"],
    auth_token=os.environ["VOBIZ_AUTH_TOKEN"],
)
```

## Receiving calls (Flask server)

When an outbound call connects (or an inbound call arrives), Vobiz requests your `answer_url` to interpret the VobizXML instructions. Use the bundled `vobizxml` builder to construct the response - it handles escaping and schema validation for you:

```python theme={null}
from flask import Flask, request, Response
from vobiz import vobizxml

app = Flask(__name__)

@app.route('/answer', methods=['GET', 'POST'])
def answer():
    call_uuid = request.values.get('CallUUID')
    from_num = request.values.get('From')
    to_num = request.values.get('To')

    print(f"Incoming call {call_uuid}: {from_num} → {to_num}")

    r = vobizxml.ResponseElement()
    r.add_speak(
        "Hello! You have reached our Python application.",
        voice="WOMAN",
        language="en-US",
    )
    r.add_hangup()

    return Response(r.to_string(), status=200, mimetype='application/xml')

if __name__ == '__main__':
    app.run(port=5001)
```

## VobizXML

The Python SDK bundles a `vobizxml` module to construct robust IVR systems without manually formatting XML. Build a `ResponseElement`, add nested verbs, and serialize with `to_string()`:

```python theme={null}
from vobiz import vobizxml

r = vobizxml.ResponseElement()

g = r.add_gather(
    action="https://your-server.com/gather-result",
    input_type="dtmf",
    num_digits=1,
    execution_timeout=10,
)
g.add_speak("Welcome to Acme Corp. Press 1 for Sales.")

r.add_hangup()

print(r.to_string())
```

<Note>
  Gather uses `input_type` and `execution_timeout` (not `timeout`). The `timeout` attribute belongs to Dial/Number elements only.
</Note>

In a webhook handler you return the serialized string with an XML mimetype:

```python theme={null}
return Response(r.to_string(), mimetype="application/xml")
```

## Common operations

### Live calls

```python theme={null}
# List in-progress calls
client.live_calls.list_live_calls(auth_id=AUTH_ID)

# Fetch a single live call
client.live_calls.get_live_call(auth_id=AUTH_ID, call_uuid="CALL_UUID")

# Hang up a live call
client.live_calls.hangup_call(auth_id=AUTH_ID, call_uuid="CALL_UUID")
```

### In-call actions

```python theme={null}
client.play_audio.call(auth_id=AUTH_ID, call_uuid="CALL_UUID", urls="https://cdn/audio.mp3")
client.speak_text.call(auth_id=AUTH_ID, call_uuid="CALL_UUID", text="Hello from Vobiz")
client.dtmf.send_dtmf(auth_id=AUTH_ID, call_uuid="CALL_UUID", digits="1234")
client.record_calls.start_recording(auth_id=AUTH_ID, call_uuid="CALL_UUID")
```

### Phone numbers and account balance

```python theme={null}
# List the numbers on your account
client.phone_numbers.list_numbers(auth_id=AUTH_ID)

# Purchase a new number out of the public inventory
client.phone_numbers.purchase_from_inventory(auth_id=AUTH_ID)

# Fetch your account balance
balance = client.balance.get_balance(auth_id=AUTH_ID, currency="INR")
print(balance)
```

### Call detail records (CDR)

```python theme={null}
cdrs = client.cdr.list_cdrs(auth_id=AUTH_ID)
recent = client.cdr.list_recent_cdrs(auth_id=AUTH_ID)
one = client.cdr.get_cdr(auth_id=AUTH_ID, call_id="CALL_ID")
```

<Note>
  Exact required parameters per method are listed in the SDK `reference.md` and at [vobiz.ai/docs](https://vobiz.ai/docs). Most write methods accept the same fields as the REST API reference.
</Note>

## Resources

* [GitHub repository](https://github.com/vobiz-ai/Vobiz-Python-SDK)
* [Vobiz Console](https://console.vobiz.ai)
* [API documentation](/docs/introduction)
* [VobizXML reference](/docs/xml/response)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.