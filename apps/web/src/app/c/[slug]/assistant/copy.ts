import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

/**
 * The words this screen writes itself (`tests/simpleCopyLegal.test.ts`). The assistant's own
 * workspace is the shared `ClientAssistantWorkspace` and its words live there.
 */
export const ASSISTANT_COPY = {
  viewAsDescription: `What ${ASSISTANT_NAME} did for this client.`,
  viewAsOff: `${ASSISTANT_NAME} is not available while you view this account.`,
  viewAsWhy: "It would spend the client's own allowance.",
} as const;
