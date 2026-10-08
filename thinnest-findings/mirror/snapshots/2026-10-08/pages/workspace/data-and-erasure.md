> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Your data: erasure and training

> What is deleted when you erase a contact, what is kept on purpose, and when recordings may be used to improve our models.

When a person asks you to forget them, one call to
[`DELETE /contacts/{id}`](/api-reference/contacts/delete-contact) does it. This
page says what that removes, what it deliberately does not, and how recordings
and transcripts are treated for model training.

## Erasing a contact

Erasing a contact removes, together and for good:

* their conversations and every message in them (the transcripts);
* their calls, queued calls, callbacks and calling-campaign entries;
* their form replies, helpdesk tickets and the follow-ups waiting on them;
* **the recordings of their calls**, wherever the audio is kept;
* any duplicate of them that was merged into the contact — the record a merge
  leaves behind still holds a name and an email, so it goes too.

It cannot be undone. To stop messaging someone without forgetting them, set
their consent to `withdrawn` instead.

### Recordings go with the contact

The audio is deleted *before* the call rows are, because the rows are the only
record of where it is:

| Where the audio is | When it is deleted |
| - | - |
| Stored by us (website calls, and phone calls on a number you brought) | Immediately. |
| The phone provider's copy (calls on a number we rent you) | Immediately, through your workspace's own account with them. |
| A copy made for model training, if the workspace was on pay-as-you-go | Immediately. |

If a file cannot be deleted at that moment — a provider is down, say — the
contact is **still erased**, and the deletion is queued and retried every night
until it succeeds. The response then carries `recordingsPending`, the number of
files still queued:

```json theme={null}
{ "recordingsPending": 1 }
```

Without it (`204`, no body) every file was already gone when the response came
back.

### What is not erased

* **Do-not-call entries are kept, on purpose.** If the person asked never to be
  called again, forgetting the number would let a campaign ring it again. The
  list holds the number and where the request came from, not their history.
* **Webhook payloads we already sent** are kept for retries and then purged
  automatically after 7 days.
* **Copies in your own systems and your vendors'.** Anything your CRM, your
  webhook receiver or your tools stored is yours to delete; erasing a contact
  here does not reach into them.

Recordings you do not erase by hand are deleted on your plan's schedule anyway;
see [Recordings](/workspace/usage#recordings).

## Model training

**Recordings and transcripts are never used to train models on Pro and above.**

On **pay-as-you-go**, a copy of a call's recording and transcript may be kept to
improve our speech and language models. If you do not want that, ask us and we
will exclude your workspace — and, for a developer, every customer workspace
under it. Exclusion also deletes the copies already made, and a very large backlog is
finished over the following nights. From then on, your calls are not copied. Calls made before the
exclusion, or while it was on, are never copied later, even if the exclusion is lifted.

Write to support from the workspace owner's address and say which workspace.
Erasing a contact deletes its training copies too, whatever the plan.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.