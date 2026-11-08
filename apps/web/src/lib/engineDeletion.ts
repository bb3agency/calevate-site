import { lookup } from "@/lib/lookup";

/**
 * An erasure certificate's `engine_deletion`: a durable status token for the voice
 * platform's own copies (`apps/workers/retention.py`, `compliance/processor_erasure.py`,
 * `compliance/engine_tenant_erasure.py`), never shown as the token itself. Shared by the
 * client's data-rights register and the operator's erasure panel so the two cannot word the
 * same certificate differently.
 *
 * A token not worded here reads as the honest "not yet confirmed", never as the raw code.
 */
const ENGINE_DELETION_COPY: Record<string, string> = {
  unconfirmed_pending_vendor_api: "deletion requested, not yet confirmed",
  not_deleted_expires_with_plan_retention:
    "not deleted at the voice platform; expires with its plan retention",
  contact_erasure_requested_in_client_workspace:
    "erasure requested in this business's own workspace at the voice platform",
  call_content_deletion_requested:
    "deletion of each call's recording, transcript and details requested at the voice platform",
  call_content_and_contact_erasure_requested:
    "deletion of each call's content and of the contact requested at the voice platform",
  agents_contacts_and_workspace_deletion_requested:
    "deletion of the account's agents, workspace and contacts requested at the voice platform",
};

export function engineDeletionCopy(status: string): string {
  if (status === "") return "not recorded";
  return lookup(ENGINE_DELETION_COPY, status) ?? "not yet confirmed";
}
