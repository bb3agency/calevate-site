> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# SIP Trunk API Reference

> API endpoints for managing SIP trunks, gateways, and phone numbers on Bolna. Create, update, list, and delete trunks programmatically.

## Endpoints

### Trunks

| Method   | Endpoint                                                            | Description            |
| -------- | ------------------------------------------------------------------- | ---------------------- |
| `POST`   | [`/sip-trunks/trunks`](/docs/api-reference/sip-trunks/create)            | Create a new SIP trunk |
| `GET`    | [`/sip-trunks/trunks`](/docs/api-reference/sip-trunks/get_all)           | List all SIP trunks    |
| `GET`    | [`/sip-trunks/trunks/{trunk_id}`](/docs/api-reference/sip-trunks/get)    | Get a single SIP trunk |
| `PATCH`  | [`/sip-trunks/trunks/{trunk_id}`](/docs/api-reference/sip-trunks/update) | Update a SIP trunk     |
| `DELETE` | [`/sip-trunks/trunks/{trunk_id}`](/docs/api-reference/sip-trunks/delete) | Delete a SIP trunk     |

### Phone Numbers

| Method   | Endpoint                                                                                             | Description                        |
| -------- | ---------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `POST`   | [`/sip-trunks/trunks/{trunk_id}/numbers`](/docs/api-reference/sip-trunks/add_number)                      | Add a phone number to a trunk      |
| `GET`    | [`/sip-trunks/trunks/{trunk_id}/numbers`](/docs/api-reference/sip-trunks/list_numbers)                    | List phone numbers on a trunk      |
| `DELETE` | [`/sip-trunks/trunks/{trunk_id}/numbers/{phone_number_id}`](/docs/api-reference/sip-trunks/remove_number) | Remove a phone number from a trunk |
