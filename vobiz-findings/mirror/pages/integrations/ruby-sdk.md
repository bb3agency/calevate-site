> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Ruby SDK

> Build Ruby and Rails voice apps with the Vobiz SDK - outbound calls, SIP trunks, DID management, and VobizXML for global calling in 130+ countries.

The official Ruby SDK for the Vobiz Voice API. Make outbound calls, manage SIP trunks, handle phone numbers, and drive live call flows directly from your Ruby on Rails or native Ruby stack.

**Source code:** [vobiz-ai/Vobiz-Ruby-SDK](https://github.com/vobiz-ai/Vobiz-Ruby-SDK)

## Installation

Requires Ruby **>= 3.3.0**. The SDK is distributed from its GitHub repo (not RubyGems). Clone it, then reference it by path in your `Gemfile`:

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Ruby-SDK.git
```

```ruby theme={null}
# Gemfile
gem "vobiz", path: "./Vobiz-Ruby-SDK"
```

Then run `bundle install`.

## Quick start

Place an outbound call. When the call connects, Vobiz queries your `answer_url` webhook, which must return a valid VobizXML document.

```ruby theme={null}
require 'vobiz'

client = Vobiz::Client.new(
  api_key: ENV['VOBIZ_AUTH_ID'],
  auth_token: ENV['VOBIZ_AUTH_TOKEN']
)

auth_id = ENV['VOBIZ_AUTH_ID']

response = client.calls.make_call(
  auth_id:       auth_id,
  from:          '14155551234',
  to:            '+919876543210',
  answer_url:    'https://yourserver.com/answer',
  answer_method: 'POST'
)

puts "Call UUID: #{response.call_uuid}"
```

## Authentication

The Ruby client uses your **Auth ID** and **Auth Token**. Find both in the [Vobiz Console](https://console.vobiz.ai).

Pass your Auth ID as `api_key` (mapped to the `X-Auth-ID` header) and your Auth Token as `auth_token` (mapped to `X-Auth-Token`). It is recommended to load credentials from environment variables:

```ruby theme={null}
require 'vobiz'

client = Vobiz::Client.new(
  api_key: ENV['VOBIZ_AUTH_ID'],
  auth_token: ENV['VOBIZ_AUTH_TOKEN']
)
```

Most API methods also take your `auth_id` as a parameter:

```ruby theme={null}
auth_id = ENV['VOBIZ_AUTH_ID']
```

## VobizXML

When Vobiz calls your `answer_url`, your webhook must respond with a VobizXML document that defines the call flow. The gem ships a builder at `Vobiz::XML` (`require "vobiz/xml"`) - each `add_*` returns the created child for nesting, and keyword args map to VobizXML attributes:

```ruby theme={null}
require "vobiz/xml"

# Example Sinatra/Rails handler returning VobizXML
post '/answer' do
  content_type 'application/xml'
  r = Vobiz::XML::Response.new
  gather = r.add_gather(
    action: "https://yourapp.com/menu-choice",
    method: "POST",
    input_type: "dtmf",          # -> inputType (Gather uses inputType / execution_timeout)
    num_digits: 1,
    execution_timeout: 10,
  )
  gather.add_speak("Press 1 for sales, 2 for support, or 0 for an operator.")
  r.add_speak("We didn't receive your input. Goodbye.")
  r.add_hangup
  r.to_s                          # pretty; r.to_s(pretty: false) for one line
end
```

<Note>Prefer the builder, but returning a raw VobizXML string also works. See the [VobizXML reference](/docs/xml/response) for all verbs and attributes.</Note>

## Common operations

### Live call text-to-speech

```ruby theme={null}
# Inject TTS dynamically into a live call
client.speak_text.call(
  auth_id:   auth_id,
  call_uuid: 'YOUR_CALL_UUID',
  text:      'Hello dynamically!',
  voice:     'WOMAN',
  language:  'en-US',
  legs:      'aleg'
)
```

### Recordings

```ruby theme={null}
recordings = client.recordings.list_recordings(auth_id: auth_id, limit: 10)
recordings.data.each { |rec| puts rec.recording_url }
```

### DID phone management

```ruby theme={null}
# List numbers you own
numbers = client.phone_numbers.list_numbers(auth_id: auth_id)

# List inventory numbers available to buy
available = client.phone_numbers.list_inventory_numbers(auth_id: auth_id)

# Purchase a number from inventory
client.phone_numbers.purchase_from_inventory(auth_id: auth_id)
```

## Error handling

The SDK raises `Vobiz::ApiError` for any non-2xx response. Inspect the exception for the status code and raw body:

```ruby theme={null}
begin
  client.calls.make_call(
    auth_id:       auth_id,
    from:          '14155551234',
    to:            '+919876543210',
    answer_url:    'https://yourserver.com/answer',
    answer_method: 'POST'
  )
rescue Vobiz::ApiError => e
  puts "Status: #{e.status_code}, Body: #{e.body}"
end
```

## Resources

* [GitHub repository](https://github.com/vobiz-ai/Vobiz-Ruby-SDK)
* [Vobiz Console](https://console.vobiz.ai)
* [API documentation](/docs/introduction)
* [VobizXML reference](/docs/xml/response)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.