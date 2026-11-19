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


def caller_locale(
    approved: Collection[str], *, call_language: str | None, agent_language: str | None
) -> str:
    """The locale to send a caller-facing template in. `approved` is the set of languages
    that template was submitted and approved in; a NULL `call_language` (an English call,
    or one whose language was never read) defers to the agent's."""
    head = language_head(call_language) or language_head(agent_language)
    if head and head in approved:
        return head
    return get_settings().whatsapp_template_locale


__all__ = ["caller_locale", "language_head"]
