"""A campaign's own script language on top of its agent's (D-994, narrowed by D-1027).

The agent keeps its defaults (its own columns, unchanged by any campaign). A campaign stores
only the language keys it sets (`campaigns.settings_overrides`), and they are laid over the
agent's row on the campaign's own engine agent only (`agents.service.campaign_agent_row`,
D-1003), so its publish, the settings drift sweep and its dials agree and the agent's own calls
keep the agent's language.

Speed, the longest call, the silence handling, re-asking, background sound and filler lines are
the agent's alone (D-1027, founder 22 Nov 2026: the campaign "only lets the user choose from
all the available agents"; those settings are configured on the agent's settings page). A
campaign stored before D-1027 may still hold such keys; they are ignored here rather than
applied, so a campaign's calls sound like its agent's.
"""

from __future__ import annotations

from typing import Any, Final

from calevate_shared.languages import LANGUAGES

from apps.api.agents.languages import MAX_REPLY_LANGUAGES, client_language_tags
from apps.api.core.errors import ProblemError

OVERRIDE_KEYS: Final = ("language_primary", "languages_extra")


def _invalid(detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="campaign_setting_invalid",
        title="Check this setting",
        detail=detail,
    )


def clean_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """The overrides as stored: only the language keys, null meaning "use the agent's"."""
    unknown = sorted(set(raw) - set(OVERRIDE_KEYS))
    if unknown:
        raise _invalid(f"These cannot be set on a campaign: {', '.join(unknown)}.")
    out: dict[str, Any] = {}
    language = raw.get("language_primary")
    if language is not None:
        if str(language) not in LANGUAGES:
            raise _invalid("Choose one of the languages offered.")
        out["language_primary"] = str(language)
    extra = raw.get("languages_extra")
    if extra is not None:
        tags = [str(tag) for tag in extra]
        allowed = client_language_tags()
        if any(tag not in allowed for tag in tags):
            raise _invalid("Choose only the languages offered.")
        if len(set(tags)) != len(tags):
            raise _invalid("Each language can be chosen only once.")
        if out.get("language_primary") in tags:
            raise _invalid("The main language is already spoken; pick the others.")
        if len(tags) > MAX_REPLY_LANGUAGES - 1:
            raise _invalid(f"An agent speaks at most {MAX_REPLY_LANGUAGES} languages.")
        out["languages_extra"] = tags
    return out


def language_overrides(stored: dict[str, Any] | None) -> dict[str, Any]:
    """The keys of a stored `settings_overrides` this release honours: the language ones."""
    return {key: value for key, value in (stored or {}).items() if key in OVERRIDE_KEYS}


def apply_overrides(agent: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    """The agent row as an `AgentConfig` is built from, with a campaign's language laid on.
    Pure: the agent's stored defaults are never written."""
    honoured = language_overrides(overrides)
    if not honoured:
        return agent
    row = dict(agent)
    if "language_primary" in honoured:
        row["language_primary"] = honoured["language_primary"]
    if "languages_extra" in honoured:
        row["languages_extra"] = list(honoured["languages_extra"])
    row["campaign_overrides"] = honoured
    return row


__all__ = [
    "OVERRIDE_KEYS",
    "apply_overrides",
    "clean_overrides",
    "language_overrides",
]
