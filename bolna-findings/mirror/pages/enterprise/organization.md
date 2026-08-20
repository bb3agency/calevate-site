> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Managing Your Organization & Team

> Learn how to manage your Bolna organization, invite team members, and configure roles and permissions for secure and efficient voice AI operations.

## Overview

Your Bolna Organization is the central hub for all your voice AI resources. It acts as a top-level container for your team members, voice agents, billing information, API keys, and overall settings. Proper organization management is key to scaling your operations securely and efficiently.

Within an organization, you can manage access for different team members, monitor usage across all your agents, and configure security policies that apply to your entire team.

<Tip>
  This is an Enterprise feature.

  Please reach out to us at [enterprise@bolna.ai](mailto:enterprise@bolna.ai) or schedule a call [https://www.bolna.ai/meet](https://www.bolna.ai/meet) for more information.
</Tip>

## Managing Team Members

You can invite new members to your organization and assign and edit roles based on their responsibilities. This ensures that team members only have access to the resources they need to perform their jobs.

<Frame caption="Team Members of your Organization are shown here">
  <img src="https://mintcdn.com/bolna-54a2d4fe/2c9R_k0fRQAdtDHj/images/organization/workspace.png?fit=max&auto=format&n=2c9R_k0fRQAdtDHj&q=85&s=3fddb8541ddd49c774905700e5a38736" alt="Bolna Organization Members page showing a list of team members with their email addresses, assigned roles, and management options" width="1653" height="375" data-path="images/organization/workspace.png" />
</Frame>

* **Invite Members**: Organization Admins can invite new users via email from the 'Members' tab in the organization settings.
* **Assign Roles**: Each member is assigned a role that dictates their level of access and permissions within the organization.
* **Edit Roles**: Organization Admins can edit the access level of existing users by selecting the organization role they want to assign to their members.

## Roles and Permissions

Bolna uses a simple two-role system to manage access control within your organization.

* **Admin**: Has full, unrestricted access to the organization. Admins can manage billing, invite or edit member roles, create and delete agents, and manage all API keys. They have complete control over all settings.

* **Member**: Has limited access designed for operational tasks. Members can place calls on existing agents. They can create and manage their own API keys but cannot access API keys belonging to the admin or other members. Members are restricted from performing most delete operations (like deleting agents).

## Editing Existing User Roles

<Frame caption="Edit current member roles by clicking on the Pencil Icon for your User">
  <img src="https://mintcdn.com/bolna-54a2d4fe/2c9R_k0fRQAdtDHj/images/organization/edit-role.png?fit=max&auto=format&n=2c9R_k0fRQAdtDHj&q=85&s=8aa8fc77b366a7e840909b58504c29f5" alt="Organization Members page highlighting the pencil edit icon next to a team member's role for updating their access level" width="516" height="325" data-path="images/organization/edit-role.png" />
</Frame>

* In order to update existing user roles, click on the Edit Icon for the user you want to edit the organization role of.

<Frame caption="Edit current member roles by clicking on the Pencil Icon for your User">
  <img src="https://mintcdn.com/bolna-54a2d4fe/2c9R_k0fRQAdtDHj/images/organization/edit-role-dialog.png?fit=max&auto=format&n=2c9R_k0fRQAdtDHj&q=85&s=ad3eb007246a034775f108fce122b903" alt="Edit member role dialog box showing a dropdown to select between Admin and Member roles for updating a team member's organization access" width="498" height="295" data-path="images/organization/edit-role-dialog.png" />
</Frame>

* This opens up a dialog box where you can update the role that you want to edit.

## Usage & Billing

The **Billing** tab provides a complete overview of your subscription, plan details, and usage metrics like total call minutes and number of active agents. You can view invoicing history and manage your payment methods here.

<Tip>
  The organization's balance is shared across all users. All usage from both Admin and Member accounts is deducted from this single, centralized balance.
</Tip>

## API Keys

Both Admins and Members can generate API keys for programmatic access. However, access is scoped based on role:

* **Admin Keys**: Have full permissions and can perform any action via the API.
* **Member Keys**: Are restricted to the same permissions as the Member role. They can be used to call agents but cannot perform most of the delete or edit actions. Members can delete and create their own API Keys while not having access to the admins or other member's keys.
