"""The language a WhatsApp from Calevate's own business account goes out in when the
recipient is a CALLER (a client's customer), not the client's owner.

A template is approved by Meta per (name, language) pair, so a send may only name a
language that template was approved in; anything else fails at Meta. Each caller-facing
template therefore declares the languages it was submitted in, and this picks one per
caller: the language the source call was held in (`calls.summary_language`), else the
agent's own (`agents.language_primary`), else the platform setting
`whatsapp_template_locale`. When the caller's language has no approved template the
platform setting is used rather than the agent's, because a Tamil caller of a Telugu agent
is no better served by Telugu than by the platform default.

Owner-facing sends (the hot-lead alert, the owner digest, the healer's pages, the
campaign-archive and account-closure notices) stay on the platform setting: one language
per business owner is the console's choice, not a caller's.
"""

from __future__ import annotations

from collections.abc import Collection

from apps.api.core.settings import get_settings


def language_head(tag: str | None) -> str:
    """The primary subtag of a BCP-47 tag (`te-IN` -> `te`), which is how Meta codes the
    Indian languages we submit in; also accepts Meta's own `en_US` spelling."""
    return (tag or "").replace("_", "-").split("-")[0].strip().lower()


#: Meta's code for the English template body.
ENGLISH: str = "en"


def caller_locale(
    approved: Collection[str],
    *,
    call_language: str | None,
    agent_language: str | None,
    call_summarised: bool = False,
) -> str:
    """The locale to send a caller-facing template in. `approved` is the set of languages
    that template was submitted and approved in.

    A NULL `call_language` means either an English call or one whose language was never read
    (`calls.summary_language`). A call that WAS summarised and has no local-language summary
    was held in English, so it gets English rather than the agent's language; only a call
    never summarised (a missed call, say) defers to the agent's."""
    if call_language is None and call_summarised:
        call_language = ENGLISH
    head = language_head(call_language) or language_head(agent_language)
    if head and head in approved:
        return head
    return get_settings().whatsapp_template_locale


__all__ = ["caller_locale", "language_head"]
