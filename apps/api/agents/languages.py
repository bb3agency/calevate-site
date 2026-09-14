"""WHICH LANGUAGES THIS PRODUCT SELLS — the API-side half of the one declaration.

`calevate_shared.languages` says what the SPEECH STACK can do: 23 languages Sarvam's STT
can transcribe, 11 its TTS can speak, and the 11-language intersection an agent can
actually hold a call in. This module says what we OFFER, which is three of them, and it is
the only place in `apps/api` that DECLARES that set. Two other modules spell the same tags
and neither is a second declaration: `compliance/disclosure.py` and `agents/handoff.py`
key their per-language SENTENCES by them, which is content for a language rather than a
list of languages, and `tests/product_languages_test.py` holds both to the offered set.

WHY IT IS A SEPARATE MODULE FROM `voices.py`, WHERE `Language` USED TO LIVE. The voice
catalogue is a list of SPEAKERS, read from the engine account and curated by an operator;
the offered language set is a commercial decision that outlives any voice in it. Keeping
`Language` inside the catalogue module made every consumer of "which languages do we sell"
import the catalogue, and made the two look like one fact. They are not: a voice arrives
and is archived; a language is added when somebody has written its disclosure sentences.

WHY A `Literal` AT ALL, WHEN THE TAGS COULD BE DERIVED. Pydantic needs a STATIC type to
turn into an OpenAPI `enum`, and that enum is what gives the generated TypeScript client
its union (`apps/web/src/lib/api/schema.d.ts`) — so a computed tuple here would cost every
screen its exhaustiveness check. The Literal is therefore the ONE remaining hand-typed
copy of the three tags, and it is held equal to `offered_language_tags()` by
`tests/product_languages_test.py`, which fails if either side moves alone. Everything else
in this tree — the labels, the filter in `voice_sync.py`, the copilot's tool enum, the
adapter's language map, the CHECK constraint on `agents.language_primary` — derives.

WHAT A WRONG LANGUAGE COSTS, AND WHY THE REFUSAL IS WRITTEN RATHER THAN GENERATED.
`Literal` alone refuses `xx-IN` with pydantic's own "Input should be 'te-IN', ..." — a
sentence `core/errors._LIBRARY_PHRASINGS` drops on purpose, because it is written for
whoever implemented the model. The three refusals below are written for whoever is holding
the request, and they differ because the MISTAKES differ: an unknown code is a typo, an
unoffered conversational language is a product boundary, and a comprehension-only language
is the dead-air failure `calevate_shared.languages` exists to prevent — the caller would be
heard perfectly and answered with silence. Naming that one in its own words is the whole
reason the shared module carries `comprehension_only` as a separate field.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Final, Literal, get_args

from calevate_shared.languages import (
    find_language,
    offered_language_tags,
    offered_languages,
)
from pydantic import BeforeValidator

__all__ = [
    "LANGUAGE_LABELS",
    "PRODUCT_LANGUAGES",
    "Language",
    "OfferedLanguage",
    "language_refusal",
]

#: THE THREE THE PRODUCT SELLS, as the wire and `agents.language_primary` spell them.
#: Telugu first: we are Telugu-first (BRD §1) and that is the column's server default, so
#: this is also the order a picker renders.
#:
#: **THE ONLY HAND-TYPED COPY OF THESE TAGS IN `apps/`, and it is not free to widen.** See
#: `calevate_shared.languages.OFFERED_LANGUAGE_IDS` for what else a fourth language needs
#: in the same change (spoken sentences, a voice, a migration); `tests/product_languages_
#: test.py` is red until all of it is there.
Language = Literal["te-IN", "hi-IN", "en-IN"]

#: The same three as a tuple, for the callers that FILTER rather than type. Read off the
#: Literal rather than retyped — an identity `get_args` for `voice_sync._offered_model`'s
#: reason: what this narrows is our own declaration, so there is nothing to assert.
PRODUCT_LANGUAGES: Final[tuple[Language, ...]] = get_args(Language)

#: How a language reads in a sentence a person approves — a copilot card, a picker, an
#: operator's table. From the shared declaration's `english_name`, so the label a client
#: reads and the label an operator reads are one string.
#:
#: Keyed by `str` and not by `Language`: the keys ARE exactly `PRODUCT_LANGUAGES` (built
#: from the same rows), and saying so with a `cast` would be an assertion the type checker
#: cannot check where a test can. `tests/product_languages_test.py` asserts the equality.
LANGUAGE_LABELS: Final[Mapping[str, str]] = {
    row.bcp47: row.english_name for row in offered_languages()
}

#: The permitted values, spelled the way a person reading a refusal needs them: the tag
#: they have to send and the language it means.
_PERMITTED: Final = ", ".join(f"{tag} ({LANGUAGE_LABELS[tag]})" for tag in offered_language_tags())


def language_refusal(value: str) -> str:
    """Why this language is refused, in a sentence the caller can act on.

    THREE GROUNDS, because three different mistakes arrive here and only one of them is a
    typo. The comprehension-only arm is the one worth reading twice: Sarvam's STT can
    transcribe twelve languages its TTS cannot speak, so an agent configured in one of
    them would understand every caller and answer none. That is not a narrower offer, it
    is a broken call, and the refusal says so rather than listing the three permitted tags
    and leaving the person to wonder what was wrong with theirs.
    """
    row = find_language(value)
    if row is None:
        head = f"“{value}” is not a language code we recognise."
    elif row.comprehension_only:
        head = (
            f"An agent cannot be set to {row.english_name}: callers speaking it are "
            "transcribed accurately, but no voice on this platform can speak it back, so "
            "the agent would hear the caller and answer with silence."
        )
    else:
        # Conversational and simply not sold — `OFFERED_LANGUAGE_IDS` is three of eleven.
        # No third arm for "neither heard nor spoken": a row that is on no vendor leg at
        # all would be a language we declared and know nothing about, and the shared
        # table has none. A branch for it would be one this suite could not reach.
        head = f"Calevate does not offer {row.english_name} yet."
    return f"{head} Choose one of: {_PERMITTED}."


def _offered(value: object) -> object:
    """Refuse a non-offered language BEFORE the `Literal` does, so the sentence is ours.

    A `BeforeValidator` and not an `AfterValidator`: after the Literal has rejected the
    value there is no field validator left to run, and the error the caller reads is the
    library's. Non-strings are passed through untouched — the Literal is the right thing
    to refuse `{"language": 7}`, and inventing a sentence about a number here would be
    this module claiming a job it does not have.
    """
    if isinstance(value, str) and value not in PRODUCT_LANGUAGES:
        raise ValueError(language_refusal(value))
    return value


#: THE TYPE EVERY WIRE FIELD THAT TAKES A LANGUAGE USES. Same OpenAPI enum as `Language`
#: (a `BeforeValidator` adds no JSON-schema of its own, which `scripts/check_openapi_fresh`
#: proves by diffing the snapshot), and a refusal a person can act on instead of one
#: written for whoever implemented the model.
#:
#: RESPONSE models use bare `Language`: what comes back is a column the CHECK constraint
#: already bounds, and a validator on the way OUT would turn a schema fault into a
#: five-hundred with a sentence addressed to a caller who did not send it.
OfferedLanguage = Annotated[Language, BeforeValidator(_offered)]
