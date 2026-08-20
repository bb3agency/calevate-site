> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Pagination for Bolna APIs

> Learn how to use pagination in Bolna Voice AI APIs using `page_number` and `page_size` to fetch results efficiently and build scalable workflows.

The endpoints also support pagination using the `page_number` and `page_size` query parameters. This allows you to fetch large sets of results in smaller, manageable chunks.

## Query Parameters

* `page_number` (integer, optional): The page of results to retrieve. Defaults to `1`. The first page starts at `1`.
* `page_size` (integer, optional): The number of results per page. Defaults to `20`. You can request up to `50` results per page.

## How it works

The API uses offset-based pagination under the hood. For example:

| page\_number | page\_size | Returned records |
| ------------ | ---------- | ---------------- |
| 1            | 10         | Records 1–10     |
| 2            | 10         | Records 11–20    |
| 3            | 5          | Records 11–15    |

## Example Request

<CodeGroup>
  ```curl example-request theme={"system"}
  GET /v2/agent/1234/executions?page_number=2&page_size=5
  ```

  ```json example-response theme={"system"}
  {
    "total": 38,
    "page": 2,
    "page_size": 5,
    "has_more": true,
    "data": [
      { "id": "ex_101", "status": "success", "created_at": "..." },
      { "id": "ex_102", "status": "failed", "created_at": "..." },
      ...
    ]
  }
  ```
</CodeGroup>

## Tips

* Use `has_more` to determine if you should fetch the next page.
* Combine pagination with filters supported in the API to narrow results efficiently.
