> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Container Images Release

> Explore the latest features, performance enhancements, and API updates in the September 2025 Bolna Self-Hosted release.

### Container Image Updates

* `ghcr.io/bolna-ai/api_server:release-250911`
* `ghcr.io/bolna-ai/ws_server:release-250911`
* `ghcr.io/bolna-ai/telephone_server:release-250911`
* `ghcr.io/bolna-ai/q_manager:release-250911`
* `ghcr.io/bolna-ai/q_worker:release-250911`
* `ghcr.io/bolna-ai/arq_worker:release-250911`

### Release Changes

* **New API for Subaccount Usage** – Extended a new endpoint to retrieve the usage of all sub-accounts. ([API doc](/docs/api-reference/sub-accounts/all_usage))

* **Enhanced Logging & Call Statuses** – Added more granular logs, additional call statuses, and exception handling to improve visibility and speed up debugging.

* **Twilio and Plivo SDK Removal** – Removed the synchronous telephony SDK packages, eliminating major bottlenecks and significantly improving call initiation performance.

* **Miscellaneous Fixes** – Addressed several minor bugs to improve overall platform stability and performance.
