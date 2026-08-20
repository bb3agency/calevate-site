> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Validation

> Run the validation checker to find errors before saving and warnings before deploying.

The editor validates your graph agent automatically before every save and on demand. Validation finds two categories of issues: **errors** that block saving and **warnings** that you can acknowledge and proceed.

***

## Running validation

Click **Validate** in the toolbar to open the validation dialog. The toolbar button shows a badge with the error count if any errors exist.

<Tip>
  Validation also runs automatically when you click **Save**. If there are errors, the save is blocked and an error toast describes the issue. Click **Validate** in the toolbar to open the full validation dialog and see all issues.
</Tip>

***

## Errors (blocking)

Errors must be fixed before the agent can be saved.

| Error                              | What it means                                                                            | How to fix                                                                                  |
| ---------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **No nodes**                       | The graph is empty.                                                                      | Add at least one node.                                                                      |
| **Missing node ID**                | A node has no ID.                                                                        | Open the node inspector and set an ID.                                                      |
| **Duplicate node IDs**             | Two or more nodes share the same ID.                                                     | Rename one so all IDs are unique.                                                           |
| **No start node**                  | No node is marked as the start node.                                                     | Select a node and click **Make start node**.                                                |
| **Missing transition target**      | A transition points to a node ID that doesn't exist.                                     | Delete the transition or rename the target node to match.                                   |
| **Unreachable tool**               | A node references a `function_call` tool that isn't defined in the agent's tools config. | Add the tool in the **Tools** tab or remove the `function_call` reference.                  |
| **Bad transition parameters**      | A transition's `parameters` field has invalid structure.                                 | Edit the transition and fix the parameters JSON (must be `{name: type}` pairs).             |
| **Invalid condition type**         | A transition has an unrecognised `condition_type`.                                       | Check the trigger type selector; it must be Intent, Rule, or Always.                        |
| **Invalid expression structure**   | A Rule transition's expression is malformed (missing `logic`, empty `conditions`).       | Open the edge inspector and ensure every condition row has a variable, operator, and value. |
| **Invalid operator**               | A condition uses an operator not in the supported list.                                  | Select a valid operator from the dropdown.                                                  |
| **Knowledge base with no vectors** | A node has a knowledge base attached but no vector IDs selected.                         | Open the node inspector and select at least one vector store, or remove the knowledge base. |

***

## Warnings (non-blocking)

Warnings don't block saving. The validation dialog lets you proceed with warnings acknowledged.

| Warning                             | What it means                                                                                    | Recommendation                                             |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------- |
| **Unreachable node**                | A node has no transitions pointing to it and is not the start node.                              | Add a transition to it or delete it.                       |
| **Empty LLM prompt**                | An LLM node has no prompt text.                                                                  | Add a prompt so the LLM knows what to do on this node.     |
| **Static node without message**     | A static node has no spoken message configured.                                                  | Open the node inspector and add a static message.          |
| **Empty intent condition**          | An Intent transition has no condition text and no label, on a node with multiple outgoing edges. | Add a condition describing when to take this transition.   |
| **Duplicate transition priorities** | Two Rule or Always transitions on the same node have the same priority value.                    | Set distinct priorities to make evaluation order explicit. |

***

## Navigating to issues

Click any issue row in the validation dialog. The dialog closes, the canvas scrolls to the affected node or transition, and the inspector opens on it. Fix the issue, then open validation again to re-check.

***

## Saving with warnings

If your graph has warnings but no errors, you can save it. Saving with warnings proceeds immediately — no confirmation dialog is shown. A toast notification confirms the save completed. Warnings are guidance, not enforcement, and do not affect runtime behaviour.
