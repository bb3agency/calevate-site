> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# PHP SDK

> Build PHP voice apps with the Vobiz SDK - outbound calls, SIP trunks, CDR, and call recording across 130+ countries including India.

The official PHP SDK for the Vobiz Voice API. Make calls, manage SIP trunks, handle CDR, record calls, configure phone numbers, and more - natively from your PHP application or framework.

**Source code:** [vobiz-ai/Vobiz-PHP-SDK](https://github.com/vobiz-ai/Vobiz-PHP-SDK)

## Installation

The SDK is distributed from its GitHub repo (not Packagist). Clone it and add it as a Composer **path** (or VCS) repository:

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-PHP-SDK.git
```

```json theme={null}
// composer.json
{
  "repositories": [
    { "type": "path", "url": "./Vobiz-PHP-SDK" }
  ],
  "require": { "vobiz/vobiz-php": "*" }
}
```

Then run `composer install`.

## Authentication

All API calls require your **Auth ID** and **Auth Token**, available in the [Vobiz Console](https://console.vobiz.ai). The first argument (`apiKey`) maps to your Auth ID and is sent as the `X-Auth-ID` header; `authToken` is sent as `X-Auth-Token`.

```php theme={null}
<?php

require 'vendor/autoload.php';

use Vobiz\VobizClient;

$client = new VobizClient(
    apiKey: getenv('VOBIZ_AUTH_ID'),       // sent as X-Auth-ID
    authToken: getenv('VOBIZ_AUTH_TOKEN')  // sent as X-Auth-Token
);
```

## Quick start

Make an outbound call:

```php theme={null}
<?php

require 'vendor/autoload.php';

use Vobiz\VobizClient;
use Vobiz\Calls\Requests\MakeCallRequest;

$authId = getenv('VOBIZ_AUTH_ID');
$client = new VobizClient(
    apiKey: $authId,
    authToken: getenv('VOBIZ_AUTH_TOKEN'),
);

$response = $client->calls->makeCall(
    $authId,                                 // your account Auth ID
    new MakeCallRequest([
        'from'         => '14155551234',     // Vobiz-enabled number or SIP URI
        'to'           => '+919876543210',   // destination in E.164 format
        'answerUrl'    => 'https://example.com/answer', // webhook returning VobizXML
        'answerMethod' => 'POST',
    ])
);
```

## VobizXML

When a call is answered, Vobiz fetches **VobizXML** from your `answerUrl` webhook to control the call. The SDK ships a builder in the `Vobiz\Xml` namespace - each `add*` returns the created child for nesting, and PHP named arguments map to VobizXML attributes:

```php theme={null}
<?php

use Vobiz\Xml\ResponseElement;

$response = new ResponseElement();
$gather = $response->addGather(
    action: 'https://yourapp.com/menu-choice',
    method: 'POST',
    inputType: 'dtmf',          // Gather uses inputType / executionTimeout
    numDigits: 1,
    executionTimeout: 10,
);
$gather->addSpeak('Press 1 for sales, 2 for support, or 0 for an operator.');
$response->addSpeak("We didn't receive your input. Goodbye.");
$response->addHangup();

header('Content-Type: application/xml');
echo $response->toString();      // pretty; $response->toString(false) for one line
```

## Resources

* [GitHub repository](https://github.com/vobiz-ai/Vobiz-PHP-SDK)
* [Vobiz Console](https://console.vobiz.ai)
* [API documentation](/docs/introduction)
* [VobizXML reference](/docs/xml/response)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.