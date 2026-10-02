> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Origination URIs

> Configure outbound SIP routing destinations on your Vobiz trunk - origination URIs control where the trunk delivers inbound traffic for termination.

## Introduction

Origination URIs define the SIP endpoints where outbound calls from your trunk will be routed. Each URI represents a destination carrier, SIP provider, PBX system, or other SIP-capable endpoint that will receive your outbound traffic.

You can configure multiple origination URIs per trunk to implement load balancing and failover strategies. The system uses priority and weight values to intelligently distribute traffic across your configured destinations, ensuring high availability and optimal resource utilization.

<Info>
  **Priority:** Lower numbers indicate higher priority. URIs with priority 1 are tried first, then priority 2 as failover, and so on.

  **Weight:** Used for load balancing among URIs with the same priority. Higher weight values receive proportionally more traffic. For example, a URI with weight 20 receives twice the traffic of one with weight 10.
</Info>

## Use Cases

* **Carrier interconnection** - Route outbound calls to your upstream carrier or SIP provider. Configure primary and backup carriers with different priorities to ensure uninterrupted service if your primary carrier experiences issues.
* **PBX integration** - Connect your trunk to an on-premises or cloud PBX system. Route calls to your FreeSWITCH, Asterisk, or other SIP-capable PBX for call processing, IVR, call routing, and other telephony features.
* **Load balancing** - Distribute call traffic across multiple SIP servers using weight-based load balancing. Configure multiple URIs with the same priority but different weights to control traffic distribution ratios.
* **Geographic redundancy** - Configure origination URIs pointing to SIP servers in different geographic regions. If one region becomes unavailable, calls automatically fail over to servers in other regions based on priority settings.

## Available Operations

1. [The Origination URI Object](/docs/trunks/origination-uri/origination-uri-object) - Learn about the structure and attributes of origination URI objects
2. [Create Origination URI](/docs/trunks/origination-uri/create-origination-uri) - Add new SIP destination endpoints for outbound call routing
3. [Retrieve All Origination URIs](/docs/trunks/origination-uri/retrieve-all-origination-uris) - List all origination URIs associated with a trunk with pagination support
4. [Update Origination URI](/docs/trunks/origination-uri/update-origination-uri) - Modify URI, priority, weight, or status of existing origination URIs
5. [Delete Origination URI](/docs/trunks/origination-uri/delete-origination-uri) - Permanently remove an origination URI from a trunk

<Tip>
  **Quick Start:** Begin by reviewing the origination URI object structure, then create your first URI to start routing outbound calls. Configure multiple URIs with different priorities for failover.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.