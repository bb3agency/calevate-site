> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Sub-Accounts for Enterprise Organizations

> Bolna AI enterprise sub-accounts let you manage multiple customers & teams with full data isolation, unified billing & centralized control.

## Overview

Bolna's Sub-Account feature is designed for enterprise organizations that need to manage multiple customers, business units, or operational environments under a single main account. This powerful organizational tool provides complete data isolation, centralized management, and scalable operations for complex voice AI deployments.

Sub-accounts enable you to create logical boundaries within your account, ensuring that different customers, departments, or projects operate independently while maintaining unified oversight and control.

<Tip>
  Sub-accounts is an Enterprise feature.

  Please reach out to us at [enterprise@bolna.ai](mailto:enterprise@bolna.ai) or schedule a call [https://www.bolna.ai/meet](https://www.bolna.ai/meet) for more information.
</Tip>

## Key Sub-account Advantages

### Complete Data Isolation

* **Customer separation**: Maintain strict boundaries between different customer data and configurations
* **Audit trails**: Comprehensive logging and monitoring for each sub-account independently

### Centralized Management & Control

* **Unified dashboard**: Manage all sub-accounts from a single enterprise control panel
* **Consolidated billing**: Streamlined invoicing and cost allocation across all sub-accounts
* **Resource allocation**: Distribute and monitor usage quotas across sub-accounts

## Primary Use Cases

### Service Providers & Agencies

Transform your voice AI service delivery with enterprise-grade multi-tenancy:

* **Customer isolation**: Each client gets their own environment with dedicated resources
* **Flexible billing**: Accurate cost tracking and billing for each client account

### Large Enterprise Organizations

Organize your voice AI infrastructure across complex organizational structures:

* **Department separation**: Sales, support, marketing, and operations teams get isolated environments
* **Regional management**: Separate voice AI deployments by geographic regions or markets
* **Product line organization**: Different products or services get dedicated sub-accounts
* **Subsidiary management**: Manage voice AI for multiple company subsidiaries independently

### Development & Testing Teams

Maintain clean separation between different environments and projects:

* **Environment isolation**: Separate development, staging, and production deployments
* **Team collaboration**: Multiple teams work on isolated projects without interference
* **Feature testing**: Test new voice AI capabilities without affecting production systems
* **A/B testing**: Run parallel experiments with completely isolated data sets

### Compliance-Heavy Industries

Meet strict regulatory and compliance requirements:

* **Healthcare**: Separate patient data and HIPAA-compliant voice AI deployments
* **Financial services**: Isolated environments for different financial products or regions
* **Government**: Secure, compliant voice AI for different agencies or departments
* **Legal**: Client-specific environments with strict confidentiality requirements

## Managing Sub Accounts

### Creation

Sub-accounts are managed within the [Organization](/docs/enterprise/organization). Only **organization admins** can create, update, or delete sub-accounts and set their concurrency.

### API Keys & Access

* Sub-accounts themselves cannot generate or manage API keys.
* When a sub-account is created, an associated API key is automatically provisioned.

### Usage & Billing

* Usage can be accessed for [each sub account's usage](/docs/api-reference/sub-accounts/usage) or by [all the sub accounts](/docs/api-reference/sub-accounts/all_usage) across the entire organization.
* Navigate to [Sub-Account Usage](https://platform.bolna.ai/dashboard/subaccounts?tab=usage) to see detailed breakdowns.
* Billing is consolidated at the **organization level**, but with granular visibility into sub-account consumption for accurate cost tracking.

### Roles & Permissions

* Only **organization admins** can create, update, or delete sub-accounts and manage their concurrency.
* Sub-accounts are **not users** — they act as logical containers for agents, call logs, and usage separation.
* Access to sub-account data is scoped by API keys.

### Concurrency

* Each sub-account has a guaranteed concurrency floor (`min_concurrency`) and an optional hard cap (`max_concurrency`); leaving the cap unset makes the sub-account elastic so it can burst into the organization's unused capacity.
* See [Concurrency management](/docs/enterprise/concurrency-management) for how guarantees, caps, and shared capacity work across the organization.

### Resource Isolation

* Sub-accounts provide isolation at the **agents and call logs** level.
* Shared resources such as **phone numbers and providers** remain available at the organization level, allowing reuse across multiple sub-accounts.
* This ensures logical boundaries while still enabling efficient resource management.

### Lifecycle Management

* Sub-accounts can be created and updated via the dashboard or API.
* Create, update, and delete are restricted to **organization admins**.

### Audit & Monitoring

* Sub-accounts maintain independent usage logs, analytics, and call histories.
* These can be viewed centrally by **Admins** using the sub-account’s associated API key or the dashboard.
* This provides enterprise-wide observability while preserving operational separation between environments.

For detailed technical implementation, see our [Sub-Account API Reference](/docs/api-reference/sub-accounts/overview).

<Tip>
  Enterprise sub-accounts are designed for organizations with complex operational needs.

  Our enterprise team will work with you to design the optimal sub-account architecture for your specific requirements.
</Tip>
