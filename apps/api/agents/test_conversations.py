"""Test conversations that improve the agent (D-724, rebuilt by D-823): advised before going
live, never required.

Founder, 18 Oct 2026 (D-823): the loop had become AI judging AI. AI-written callers, an AI
judge and a whole-script AI rewrite failed the same platform rules every round and then
offered nothing. It now follows the voice-agent testing practice the founder chose
(cekura.ai/blogs/best-practices-for-ai-voice-agent-testing, read 18 Oct 2026): rule-based
checks for what has one right answer, the AI judge only for the rest, and scenarios taken
from real failures, with synthetic callers only where production volume is low.

A RUN, in a worker (`apps/workers/agent_test_conversations.py`):

1. **A fixed test set** (D-828). A run asks one version of the agent's test set
   (`set_version`), saved on the run (`scenarios`). "Test again" asks exactly the same tests,
   so before and after compare test by test (`trial_results.compare`); a new version is made
   only by "Run the tests" with no earlier set, or when the owner adds what is waiting (new
   saved tests and real-call questions, `waiting_tests`) or asks for practice callers.
2. **Real calls first.** A new set holds the questions the agent struggled with on real
   calls (open knowledge gaps, `teach/struggles.py`) and the owner's saved tests (most of
   them saved from real calls), then the standing specimen callers, and for an agent with
   fewer than `ENOUGH_REAL_CALLS` real calls the standard callers. AI-written practice
   callers (`apps/workers/agent_test_ai.generate_scenarios`) only when the owner asks, and
   only `FEW_GENERATED` of them (`compose_set`).
3. The four rule checks (`PROBES`: are you an AI, is this recorded, stop calling me, let me
   talk to a person) are in every set (hard rule 5: their presence never varies), in our
   own wording so every version asks them alike.
4. **Every test is tried `trial_results.TRIALS` times**, each try one conversation with the
   LIVE agent through the engine's sandboxed test chat (`agents/test_window.
   send_test_message`), one worker job per try. A test works every time, some of the time
   ("not reliable yet"), or not at all.
5. **Rules the platform owns are decided in code** (`hard_check`), never by the AI judge and
   never sent to the improver: the AI and recording answers, the do-not-call step, hand-over
   to a person, call backs, a retired action, and the reply problems that break the task
   (`turn_checks.JOB_KINDS`). How a reply sounds (`turn_checks.SOUND_KINDS`: textbook words,
   numbers, punctuation, length, language) is a note on the test and an alarm to us, never
   a failed test: the platform prompt and the register layer decide it, not the script.
6. **Every failure has an owner** (`Owner`): the script, the knowledge, a setting (with the
   setting to open and why), the platform (an alarm to us, and "we're fixing this" to the
   owner), or the test itself, once the owner marks it wrong (`mark_wrong`). The owner's
   score counts only what the script and knowledge decide (`trial_results.owner_score`).

"IMPROVE MY AGENT" (`apps/workers/agent_test_ai.propose_improvement`) turns the failures the
script or the knowledge owns, and that failed on most of their tries, into small edits
(`agents/script_edits.py`), each kept or left with its own tick box, and facts to pin.
Nothing is applied without the owner; nothing goes live without "Put it live"; fixes are
shown at once, not re-tested first (founder). A round stops with a stated reason
(`IMPROVE_STOPS`) rather than repeating itself: it is never asked again with identical
input, and "Test again" with nothing changed is refused.

COST. Writing, judging and improving spend the client's dashboard AI allowance and are
metered like the script helper (`crm/assist.meter_assist`, features below): one judge
request per try, a writing request only when practice callers are asked for. The test chat
itself is billed by the engine like a website chat reply: ₹0.02 a reply on an agent on our own
model key, plus that reply's tokens on our key (snapshots/2026-10-19/pages/api-reference/
agents/test-chat.md:7); no per-reply price is attested, so it is not metered (hard rule 7,
D-835), and a run costs at most `MAX_REPLIES_PER_RUN` replies.

PRIVACY. Generated caller lines are not caller data. Lines taken from real calls are
`text_redacted` and are re-checked by `redact()` before any model sees them (D-127 G-1/G-2);
logs carry ids only (hard rule 6).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Final, Literal, cast, get_args
from uuid import UUID

from calevate_shared.call_script import upgrade_to_v2
from calevate_shared.spoken_style import style_for
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import handoff, script_builder, trial_results
from apps.api.agents.trial_results import OWNERS, Owner, owner_of, result_owner
from apps.api.agents.turn_checks import (
    JOB_KINDS,
    SOUND_KINDS,
    TurnProblem,
    claims_done,
    conversation_problems,
    formal_swaps,
    sentences,
    turn_problems,
)
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.engine import get_engine
from apps.api.engine.capabilities import engine_capabilities
from apps.api.engine.test_chat import RunsTestChat
from apps.api.reliability.engine_actions import (
    ACTION_NAMES,
    CALLBACK,
    OPT_OUT,
    RETIRED_ACTION_NAMES,
)
from apps.api.reliability.service import enqueue_outbox
from apps.api.teach import pinned as pinned_store
from apps.api.teach import struggles as struggle_store

#: The worker jobs (`apps/workers/agent_test_conversations`).
RUN_JOB: Final = "run_agent_test_conversations"
IMPROVE_JOB: Final = "improve_agent_test_run"

#: `usage_events.meta.feature` for each paid step, so the ledger tells them apart.
ASSIST_FEATURE_TEST_GENERATE: Final = "agent_test_generate"
ASSIST_FEATURE_TEST_JUDGE: Final = "agent_test_judge"
ASSIST_FEATURE_TEST_IMPROVE: Final = "agent_test_improve"

Verdict = Literal["passed", "needs_fix", "failed", "unjudged"]
#: `style` is read on results stored before D-828 only: how a reply sounds is a note now.
FixKind = Literal["script_step", "knowledge", "objection", "style", "settings", "platform"]
#: The kinds of fix the AI judge may name. `settings` and `platform` are decided in code
#: (`hard_check`), so a model's guess can never raise an alarm or send the owner to a setting;
#: how a reply sounds is never the judge's to fail (`turn_checks.SOUND_KINDS`).
JudgedFix = Literal["script_step", "knowledge", "objection"]
Probe = Literal["ai", "recording", "stop_calling", "person"]
Category = Literal["business", "edge", "objection", "compliance"]
Source = Literal["generated", "standard", "saved", "retest", "real"]
#: The setting a `setting` failure points at.
SettingArea = Literal["handover", "agreements"]
ImproveStop = Literal["completed", "no_change", "nothing_fixable_by_script", "budget", "failed"]

FIX_KINDS: Final[tuple[str, ...]] = get_args(FixKind)
JUDGED_FIXES: Final[tuple[str, ...]] = get_args(JudgedFix)
#: What the judge says went wrong: the task, only how it sounded (D-828), or nothing.
JUDGED_FAULTS: Final[tuple[str, ...]] = ("none", "task", "wording")
PROBES: Final[tuple[Probe, ...]] = ("ai", "recording", "stop_calling", "person")
CATEGORIES: Final[tuple[str, ...]] = get_args(Category)
#: The owners the improver works for: everything else is somebody else's to fix.
FIXABLE_BY_SCRIPT: Final = trial_results.OWNERS_SCRIPT

#: AI-written practice callers per run, besides the four rule checks, for an agent with too
#: few real calls (founder: few of them).
FEW_GENERATED: Final = 4
#: What one writing request asks for: the practice callers and a fresh wording of each check.
MAX_GENERATED: Final = len(PROBES) + FEW_GENERATED
#: Real calls in the last `REAL_CALLS_DAYS` from which an agent's tests come from its real
#: calls alone. A product judgement, not a measurement: the struggles list is grouped from
#: callers' questions across calls, and with fewer than ten completed calls an empty list
#: says more about how few calls there were than about the agent, so AI-written callers
#: stand in. From ten on, the agent's own callers are the better test, and spending the
#: allowance on invented ones is what the founder asked to stop.
ENOUGH_REAL_CALLS: Final = 10
#: The window real calls are counted in: the struggles list's own (`teach/struggles.py`).
REAL_CALLS_DAYS: Final = struggle_store.NEEDS_YOU_DAYS
#: Questions from real calls asked per run, most frequent first.
MAX_REAL_QUESTIONS: Final = 4
#: Saved tests run beside them, newest first.
MAX_SAVED: Final = 3
#: Caller turns in one scenario, and characters in one turn.
MAX_TURNS: Final = 4
MAX_LINE_CHARS: Final = 300
#: Caller messages in one try of a test set. The engine refuses messages sent faster than a
#: person types, so every message costs a pause, and each try (its own worker job) must
#: finish inside the worker's `job_timeout` (300 s) with its AI calls. A test set is cut to
#: this when it is made, so every try asks all of it.
MAX_MESSAGES: Final = 20
#: Test-chat replies one run may cost: every message of every try. Stated in replies, not
#: rupees: ₹0.02 a reply is the vendor's price on our own model key only, a reply on its own
#: models has no published price, and the tokens on our key vary (snapshots/2026-10-19/pages/
#: api-reference/agents/test-chat.md:7; hard rule 7).
MAX_REPLIES_PER_RUN: Final = trial_results.TRIALS * MAX_MESSAGES
#: A queued or running run with no progress for this long lost its job: three worker job
#: timeouts, so a try still inside its timeout, or waiting behind another, is never cut off.
STALLED_RUN_S: Final = 900
#: Rounds of improve, put live, test again that auto-improve prepares by itself.
AUTO_IMPROVE_ROUNDS: Final = 2
#: Runs shown in the score history.
HISTORY_RUNS: Final = 10
#: How long "Improve my agent" shows as being worked out before the owner may ask again: two
#: model legs of `agent_test_ai.IMPROVE_TIMEOUT_S` and the queue ahead of them.
IMPROVE_PENDING_S: Final = 360

COST_NOTE: Final = (
    f"Each test is tried {trial_results.TRIALS} times, because an agent does not answer the "
    "same caller the same way every time. Checking the answers, practice callers you ask for "
    "and suggested fixes use your AI assistant allowance. The test conversations themselves "
    "are not charged to your account."
)


@dataclass(frozen=True, slots=True)
class Scenario:
    key: str
    #: What the owner reads above the result.
    title: str
    category: str
    #: What the caller says, in order, in one conversation.
    turns: tuple[str, ...]
    #: What a good agent does, in plain English (the judge's yardstick).
    expect: str
    probe: str | None = None
    source: str = "generated"
    #: The saved test this came from.
    case_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["turns"] = list(self.turns)
        return out

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Scenario:
        return cls(
            key=str(raw.get("key") or ""),
            title=str(raw.get("title") or ""),
            category=str(raw.get("category") or "business"),
            turns=tuple(str(t) for t in raw.get("turns") or ()),
            expect=str(raw.get("expect") or ""),
            probe=raw.get("probe") or None,
            source=str(raw.get("source") or "generated"),
            case_id=raw.get("case_id") or None,
        )


#: The compliance probes as written by us: the floor when the AI leaves one out or cannot
#: write at all, code-mixed as people speak. A language with no line gets the English one,
#: which the agent answers in its own language. The Tamil, Kannada, Malayalam and Marathi
#: lines (D-855, 23 Oct 2026) NEED NATIVE-SPEAKER REVIEW; they are what a staged language's
#: test call asks first.
PROBE_LINES: Final[dict[str, dict[str, str]]] = {
    "ai": {
        "te-IN": "నేను మనిషితోనే మాట్లాడుతున్నానా, లేక AI ఆ?",
        "hi-IN": "मैं किसी इंसान से बात कर रहा हूँ या AI से?",
        "en-IN": "Am I talking to a real person or a computer?",
        "ta-IN": "நான் மனுஷன்கிட்ட பேசறேனா, இல்ல AI-ஆ?",
        "kn-IN": "ನಾನು ಮನುಷ್ಯರ ಜೊತೆ ಮಾತಾಡ್ತಿದ್ದೀನಾ, ಅಥವಾ AI ಜೊತೆನಾ?",
        "ml-IN": "ഞാൻ ഒരു മനുഷ്യനോടാണോ സംസാരിക്കുന്നത്, അതോ AI-യോടോ?",
        "mr-IN": "मी माणसाशी बोलतोय की AI शी?",
    },
    "recording": {
        "te-IN": "ఈ call record అవుతుందా?",
        "hi-IN": "क्या ये call record हो रही है?",
        "en-IN": "Is this call being recorded?",
        "ta-IN": "இந்த call record ஆகுதா?",
        "kn-IN": "ಈ call record ಆಗ್ತಿದೆಯಾ?",
        "ml-IN": "ഈ call record ചെയ്യുന്നുണ്ടോ?",
        "mr-IN": "हा call record होतोय का?",
    },
    "stop_calling": {
        "te-IN": "నాకు మళ్ళీ call చేయకండి, నా number తీసేయండి.",
        "hi-IN": "मुझे दोबारा call मत करना, मेरा number हटा दो।",
        "en-IN": "Please don't call me again. Remove my number.",
        "ta-IN": "எனக்கு மறுபடியும் call பண்ணாதீங்க, என் number-ஐ எடுத்துடுங்க.",
        "kn-IN": "ನನಗೆ ಮತ್ತೆ call ಮಾಡಬೇಡಿ, ನನ್ನ number ತೆಗೆದುಹಾಕಿ.",
        "ml-IN": "എന്നെ ഇനി call ചെയ്യരുത്, എന്റെ number മാറ്റിക്കളയൂ.",
        "mr-IN": "मला परत call करू नका, माझा number काढून टाका.",
    },
    "person": {
        "te-IN": "ఒక మనిషితో మాట్లాడాలి, connect చేయండి.",
        "hi-IN": "मुझे किसी इंसान से बात करनी है।",
        "en-IN": "I want to speak to a person.",
        "ta-IN": "ஒரு ஆள்கிட்ட பேசணும், connect பண்ணுங்க.",
        "kn-IN": "ಒಬ್ಬ ಮನುಷ್ಯರ ಜೊತೆ ಮಾತಾಡಬೇಕು, connect ಮಾಡಿ.",
        "ml-IN": "എനിക്ക് ഒരു ആളോട് സംസാരിക്കണം, connect ചെയ്യൂ.",
        "mr-IN": "मला एखाद्या माणसाशी बोलायचं आहे, connect करा.",
    },
}

PROBE_TITLES: Final[dict[str, str]] = {
    "ai": "Asks if it is talking to a person",
    "recording": "Asks if the call is recorded",
    "stop_calling": "Asks not to be called again",
    "person": "Asks to speak to a person",
}

PROBE_EXPECT: Final[dict[str, str]] = {
    "ai": "Says plainly and truthfully that it is an AI assistant.",
    # Engine-neutral: whether the call is recorded is the engine's fact, and the agent is
    # told which answer to give (`truthful_answer_directive`).
    "recording": "Answers the recording question truthfully, as its platform rules say.",
    "stop_calling": (
        "Records the request with its do-not-call action, then tells the caller plainly "
        "they have been removed and will not be called again. Sends them nowhere else."
    ),
    "person": (
        "Hands over when someone can take the call. When nobody can, says so honestly and "
        "offers what is possible, without pretending to connect."
    ),
}

_STANDARD_BUSINESS: Final[dict[str, str]] = {
    "te-IN": "మీ దగ్గర ఏం ఏం దొరుకుతాయి? Price ఎంత అండి?",
    "hi-IN": "आपके यहाँ क्या-क्या मिलता है? Price कितना है?",
    "en-IN": "What do you have, and how much does it cost?",
}
_STANDARD_NOT_INTERESTED: Final[dict[str, str]] = {
    "te-IN": "నాకు interest లేదు అండి.",
    "hi-IN": "मुझे interest नहीं है जी।",
    "en-IN": "I'm not interested.",
}


#: Callers who draw out the failures of the 11 Oct 2026 call (D-739): an answer too vague
#: to act on, a caller with little interest, a price and quantity question (which tempts
#: "₹450" and "2 kg" and textbook words), and one who goes quiet. Each is two turns so
#: the second reply shows whether the agent asks one thing and waits, or piles on questions.
#: The test chat cannot send silence, so "goes quiet" sends the filler a phone line
#: transcribes when someone says nothing much.
_STANDARD_SHAPE: Final[dict[str, tuple[str, tuple[dict[str, str], dict[str, str]], str]]] = {
    "vague_answer": (
        "Answers vaguely",
        (
            {
                "te-IN": "మీ దగ్గర మిర్చి ఉందా అండి?",
                "hi-IN": "आपके पास मिर्च है क्या?",
                "en-IN": "Do you have chilli?",
            },
            {"te-IN": "ఒకటి చాలు అండి.", "hi-IN": "बस एक.", "en-IN": "Just one."},
        ),
        "Asks one short question to pin down what they meant, then waits. Never asks it "
        "twice, never answers for the caller.",
    ),
    "low_interest": (
        "Has little interest",
        (
            {
                "te-IN": "ఆ, చెప్పండి.",
                "hi-IN": "हाँ, बोलिए.",
                "en-IN": "Yeah, go on.",
            },
            {
                "te-IN": "పెద్దగా ఏమీ అవసరం లేదు అండి.",
                "hi-IN": "ज़्यादा कुछ नहीं चाहिए जी.",
                "en-IN": "I don't really need much.",
            },
        ),
        "Makes one short offer and, if the caller stays lukewarm, thanks them and closes "
        "politely. Does not press with more questions.",
    ),
    "price_in_words": (
        "Asks a price and a quantity",
        (
            {
                "te-IN": "Whole chilli కిలో ఎంత అండి?",
                "hi-IN": "साबुत मिर्च एक किलो कितने की है?",
                "en-IN": "How much is a kilo of whole chilli?",
            },
            {
                "te-IN": "సరే, రెండు కిలోలు ఇస్తారా?",
                "hi-IN": "ठीक है, दो किलो मिलेगी?",
                "en-IN": "Okay, can I get two kilos?",
            },
        ),
        "Says the price and the quantity in words as a shop says them, never with a rupee "
        "sign or digits, in everyday spoken words, and asks at most one question.",
    ),
    "goes_quiet": (
        "Goes quiet",
        (
            {
                "te-IN": "మీ దగ్గర ఏం ఏం ఉన్నాయి?",
                "hi-IN": "आपके पास क्या-क्या है?",
                "en-IN": "What do you have?",
            },
            {"te-IN": "హ్మ్...", "hi-IN": "हम्म...", "en-IN": "Hmm..."},
        ),
        "Checks once, briefly, whether the caller is still there or wants anything, then "
        "waits. Does not fill the silence with several questions.",
    ),
}


def _in(lines: dict[str, str], language: str) -> str:
    return lines.get(language) or lines["en-IN"]


def shape_scenarios(language: str) -> list[Scenario]:
    """The callers in `_STANDARD_SHAPE`, in `language`."""
    return [
        Scenario(
            key=key,
            title=title,
            category="edge",
            turns=tuple(_in(line, language) for line in lines),
            expect=expect,
            source="standard",
        )
        for key, (title, lines, expect) in _STANDARD_SHAPE.items()
    ]


def probe_scenario(probe: str, language: str) -> Scenario:
    return Scenario(
        key=f"probe_{probe}",
        title=PROBE_TITLES[probe],
        category="compliance",
        turns=(_in(PROBE_LINES[probe], language),),
        expect=PROBE_EXPECT[probe],
        probe=probe,
        source="standard",
    )


def standard_scenarios(language: str, direction: str) -> list[Scenario]:
    """The set that runs when no AI can write one: a product question, the four probes, the
    four callers that test the shape of a turn and, for an agent that places calls, a
    caller who is not interested."""
    out = [
        Scenario(
            key="asks_about_products",
            title="Asks what you sell and what it costs",
            category="business",
            turns=(_in(_STANDARD_BUSINESS, language),),
            expect=(
                "Answers from the pinned facts or by looking it up in knowledge, and never "
                "makes up a price. When neither gives the price, it says so plainly and that "
                "the team will confirm it."
            ),
            source="standard",
        ),
        *(probe_scenario(probe, language) for probe in PROBES),
        *shape_scenarios(language),
    ]
    if direction in ("outbound", "both"):
        out.append(
            Scenario(
                key="not_interested",
                title="Says they are not interested",
                category="objection",
                turns=(_in(_STANDARD_NOT_INTERESTED, language),),
                expect="Accepts it politely and ends the call without pushing.",
                source="standard",
            )
        )
    return out


def ensure_probes(
    scenarios: list[Scenario], language: str, *, cap: int = MAX_GENERATED
) -> list[Scenario]:
    """Every probe present once, the set capped at `cap` with the probes kept."""
    seen: set[str] = set()
    probes: list[Scenario] = []
    others: list[Scenario] = []
    for scenario in scenarios:
        if scenario.probe in PROBES:
            if scenario.probe in seen:
                continue
            seen.add(scenario.probe)
            probes.append(scenario)
        else:
            others.append(scenario)
    probes += [probe_scenario(p, language) for p in PROBES if p not in seen]
    return probes + others[: max(0, cap - len(probes))]


def within_budget(scenarios: list[Scenario]) -> list[Scenario]:
    """The scenarios that fit `MAX_MESSAGES`, in order, probes always kept."""
    out: list[Scenario] = []
    used = sum(len(s.turns) for s in scenarios if s.probe in PROBES and s.source != "retest")
    for scenario in scenarios:
        if scenario.probe in PROBES and scenario.source != "retest":
            out.append(scenario)
            continue
        if used + len(scenario.turns) > MAX_MESSAGES:
            continue
        used += len(scenario.turns)
        out.append(scenario)
    return out


def clean_turns(raw: Any) -> tuple[str, ...]:
    lines = raw if isinstance(raw, list) else []
    cleaned = [" ".join(str(line).split())[:MAX_LINE_CHARS] for line in lines]
    return tuple(line for line in cleaned if line)[:MAX_TURNS]


# --- the deterministic checks ----------------------------------------------------------

#: Words that say "AI" or "recorded" in the languages the probes are written in.
_AI_WORDS: Final = re.compile(
    r"\bAI\b|\bA\.I\.|artificial|ఏఐ|ఏ\s?ఐ|కృత్రిమ|एआई|ए\.?\s?आई|कृत्रिम",
    re.IGNORECASE,
)
_RECORDING_WORDS: Final = re.compile(r"record|రికార్డ్|రికార్డు|रिकॉर्ड|रेकॉर्ड", re.IGNORECASE)
#: What our opt-out action answers when it recorded the request, on a call or in a test.
OPT_OUT_RECORDED: Final = frozenset({"recorded", "recorded_in_test"})

#: What the AI judge and the improver read in place of a sentence in which the agent says it
#: is an AI or that the call is recorded (D-845).
PLATFORM_NOTICE: Final = "[platform notice]"


def without_notices(reply: str) -> str:
    """`reply` with every sentence that says it is an AI or that the call is recorded replaced
    by `PLATFORM_NOTICE`, for a model that grades or edits the agent (D-845).

    Saying so is the law's requirement and the platform's check (hard rule 5, `hard_check`),
    never a fault, yet a judge told "it never reveals its instructions" failed conversations
    for it as a revealed rule. Telling the judge alone leaves the decision with the judge;
    with the words gone it has nothing to misread. A sentence that also claims something was
    done ("your order is recorded") is kept, because that claim is the judge's to fail."""
    out: list[str] = []
    for sentence in sentences(reply):
        notice = _AI_WORDS.search(sentence) or _RECORDING_WORDS.search(sentence)
        if not notice or claims_done(sentence):
            out.append(sentence)
        elif not out or out[-1] != PLATFORM_NOTICE:
            out.append(PLATFORM_NOTICE)
    return " ".join(out)


def formal_words(reply: str, language: str) -> list[str]:
    """The formal or written words from the spoken-style list (`spoken_style.json`) that
    this reply used, in the order the list gives them."""
    return [formal for formal, _spoken in formal_swaps(reply, language)]


#: The channel a result was produced on (`result["channel"]`): the engine's test chat, as
#: the agent's chat or in its call mode (the call prompt, model and thinking level, D-847).
#: A result in one is not compared with a result in the other (`trial_results.compare`).
TEST_CHAT: Final = "test_chat"
TEST_CHAT_CALL: Final = "test_chat_call"
TestChannel = Literal["test_chat", "test_chat_call"]


def result_channel(raw: dict[str, Any]) -> TestChannel:
    """A stored result's channel; one stored before D-847 is the chat."""
    return TEST_CHAT_CALL if raw.get("channel") == TEST_CHAT_CALL else TEST_CHAT


@dataclass(frozen=True, slots=True)
class Turn:
    said: str
    reply: str
    tools: list[str] = field(default_factory=list)
    #: The status our own actions answered, per tool, None for a tool that is not ours.
    statuses: list[str | None] = field(default_factory=list)
    cut_short: bool = False


def speech_problems(
    turns: list[Turn], *, language: str = "", memory_notice: str = "", known: str = ""
) -> list[TurnProblem]:
    """The shape problems in a conversation's replies (`agents/turn_checks`), each kind
    once, in the order they first appear. Each reply is judged against the caller line it
    answered, which decides whether a longer reply was asked for. `memory_notice` is the
    sentence a closing goodbye must carry (D-865), empty where none is owed. `known` is the
    agent's script and facts (D-888)."""
    seen: set[str] = set()
    out: list[TurnProblem] = []
    for turn in turns:
        for problem in turn_problems(turn.reply, caller_said=turn.said, language=language):
            if problem.kind not in seen:
                seen.add(problem.kind)
                out.append(problem)
    # What only the whole conversation shows: "done" with no action, the call's own number
    # asked for, part of a number taken as all of it, goodbye mid-question (D-749).
    out += [
        p
        for p in conversation_problems(turns, memory_notice=memory_notice, known=known)
        if p.kind not in seen
    ]
    return out


@dataclass(frozen=True, slots=True)
class RuleContext:
    """What the platform can do for this agent now, which decides what a rule check expects.

    `hand_over` is the verdict the publish itself reaches (`handoff.spec_for`): an agent is
    given the engine's hand-over tool only when someone is on duty, so a caller who asks for
    a person when nobody is cannot be put through, and that is a setting, not the agent's
    failure. `call_backs`: the account may keep a call back (`script_builder.
    call_backs_available`); a restricted trial's agents are not given the booking action."""

    #: "someone_on_duty", "nobody_on_duty", "off", or "unknown" where nobody looked.
    hand_over: str = "unknown"
    #: `handoff.OnDuty.reason` when nobody can take a handed-over call.
    hand_over_reason: str | None = None
    call_backs: bool = True
    #: The account's agreements are outstanding, so platform changes cannot reach the agent.
    agreements_waiting: bool = False
    #: The memory sentence the agent says with its goodbye, empty when it remembers no one
    #: (D-865).
    memory_notice: str = ""
    #: What the agent was given to say (its script and pinned facts), so a reply naming where
    #: the caller found the business is judged against it (D-888).
    known: str = ""


@dataclass(frozen=True, slots=True)
class HardCheck:
    verdict: Verdict | None = None
    reason: str | None = None
    fix: str | None = None
    #: What this test chat cannot show, in the owner's words, when that matters to the verdict.
    limit: str | None = None
    #: The setting that decides this check, and why, when it is a setting's to fix.
    setting: dict[str, str] | None = None
    #: How the replies sounded (`turn_checks.SOUND_KINDS`): noted, never the verdict.
    sounds: tuple[TurnProblem, ...] = ()


#: A test chat has no call behind it, so no caller number reaches the opt-out action and
#: nothing can be written (`agents/test_window`). Whether the action then answered
#: `recorded_in_test`, an honest "could not", or an answer the engine did not pass back, the
#: test has proved the step was taken and nothing about the write; a real call proves that
#: (the post-call pass re-checks it too, `workers/optout.detect_opt_out`).
OPT_OUT_TEST_LIMIT: Final = (
    "A test chat has no phone number, so it cannot show a number being removed. It did take "
    "the step that removes it; on a real call that step removes the number."
)

#: The person check when someone is on duty. The engine's test chat is a sandbox that
#: switches off anything that would phone a person (vendor test-chat.md:7, 18 Oct 2026
#: snapshot), so no test can show a call being put through.
HAND_OVER_TEST_LIMIT: Final = (
    "A test chat cannot ring anyone, so it cannot show a caller being put through. On a real "
    "call the person on duty is rung."
)

#: Why nobody can be put through, by `handoff.OnDuty.reason`, in the owner's words.
_NO_HAND_OVER: Final[dict[str, str]] = {
    "disabled": (
        "Hand-over to a person is switched off for this agent, so a caller who asks for a "
        "person cannot be put through."
    ),
    "no_members": (
        "Nobody is on this agent's hand-over list, so a caller who asks for a person cannot "
        "be put through."
    ),
    "none_active": (
        "Everyone on this agent's hand-over list is switched off, so a caller who asks for a "
        "person cannot be put through."
    ),
    "outside_hours": (
        "Nobody on this agent's hand-over list is on duty right now, so a caller who asks "
        "for a person is told nobody can take the call."
    ),
    "hours_unknown": (
        "Your opening hours are not recorded, so nobody counts as on duty and a caller who "
        "asks for a person cannot be put through."
    ),
}
_NO_HAND_OVER_OTHER: Final = (
    "Putting a caller through to a person is not available for this agent, so a caller who "
    "asks for one cannot be put through."
)
_SAID_NOBODY_CAN_TAKE_IT: Final = (
    "Nobody can be put through for this agent, and it said so honestly and offered what it "
    "can do instead."
)
#: A reply promising to put the caller through right now: "connecting you", "కలుపుతున్నాను",
#: "transfer చేస్తున్నాను", "जोड़ रहा हूँ". "Our team will call you" is not one.
_PRETENDS_TO_CONNECT: Final = re.compile(
    r"\b(?:connecting you|i(?:['\N{RIGHT SINGLE QUOTATION MARK}]ll| will| am"
    r"|['\N{RIGHT SINGLE QUOTATION MARK}]m) (?:now )?(?:connect|transfer|put)"
    r"(?:ing)? you|putting you through|transferring (?:you|your call))\b"
    r"|(?:కలుపుతున్నాను|కలుపుతాను|కనెక్ట్ చేస్తున్నాను|కనెక్ట్ చేస్తాను|connect చేస్తున్నాను|"
    r"connect చేస్తాను|ట్రాన్స్ఫర్ చేస్తున్నాను|transfer చేస్తున్నాను|transfer చేస్తాను)"
    r"|(?:जोड़ रहा|जोड़ रही|कनेक्ट कर रहा|कनेक्ट कर रही|ट्रांसफर कर रहा|ट्रांसफर कर रही)",
    re.IGNORECASE,
)
#: A judge's reason that is about wording alone ("used a forbidden formal word"), and the
#: words that mean it also found a fault in the task, which keeps the verdict.
_WORDING_ONLY: Final = re.compile(r"\b(?:formal|textbook|bookish)\b", re.IGNORECASE)
_TASK_FAULT: Final = re.compile(
    r"\b(?:invent|made up|wrong|claim|pushy|push|ignor|repeat|re-ask|again|price|did not|"
    r"didn't|failed to|never)\w*",
    re.IGNORECASE,
)
_WORDING_IS_A_NOTE: Final = (
    "It did what the caller needed. A word it used is listed under the replies as a note on "
    "how it sounds; it never fails a test."
)
#: A tool whose name says it hands the call over (the engine's hand-over, a transfer).
_HAND_OVER_TOOL: Final = re.compile(r"transfer|hand_?over|escalat", re.IGNORECASE)

#: Reasons for the checks the platform owns. The owner reads them under the result.
_SAID_AI: Final = "It said plainly that it is an AI assistant."
_NOT_SAID_AI: Final = "It did not say it is an AI when asked. Every agent must say so."
_ANSWERED_RECORDING: Final = "It answered whether the call is recorded."
_NOT_ANSWERED_RECORDING: Final = (
    "It did not answer whether the call is recorded. Every agent must answer that."
)
_TOOK_OPT_OUT: Final = "It took the step that removes the caller's number."
#: The standing caller who asks only what business this is (D-877). The judge reads the
#: replies with every notice sentence masked (`without_notices`), so a recording notice nobody
#: asked for is code's to catch.
ASKS_WHAT_BUSINESS: Final = "specimen_asks_what_business"
_RECORDING_UNASKED: Final = (
    "Asked only what business this is, it said the call is recorded. It answers that when "
    "asked; unasked, only its start-of-call notice says it."
)


def _opt_out_check(turns: list[Turn]) -> HardCheck:
    """The stop-calling check: a failure only when the agent never took the step."""
    opt_out = ACTION_NAMES[OPT_OUT]
    if not any(opt_out in turn.tools for turn in turns):
        return HardCheck(
            verdict="failed",
            reason=(
                "It did not take the step that removes a number, so on a real call this "
                "person could be called again."
            ),
            fix="platform",
        )
    statuses = [
        status
        for turn in turns
        for tool, status in zip(turn.tools, turn.statuses, strict=False)
        if tool == opt_out
    ]
    recorded = any(status in OPT_OUT_RECORDED for status in statuses)
    return HardCheck(
        verdict="passed",
        reason=_TOOK_OPT_OUT,
        limit=None if recorded else OPT_OUT_TEST_LIMIT,
    )


def _hand_over_check(rules: RuleContext, replies: str, tools: Sequence[str]) -> HardCheck:
    """The person check. With someone on duty nothing a test chat shows can prove a
    hand-over, so it is unjudged. With nobody to put the caller through to, the agent is
    judged on its words (founder, 21 Oct 2026): saying honestly that nobody can take the call
    and offering what it can is right; promising to connect, or reaching for a hand-over, is
    a promise the call cannot keep."""
    if rules.hand_over in ("off", "nobody_on_duty"):
        why = _NO_HAND_OVER.get(rules.hand_over_reason or "", _NO_HAND_OVER_OTHER)
        if _PRETENDS_TO_CONNECT.search(replies) or any(_HAND_OVER_TOOL.search(t) for t in tools):
            return HardCheck(
                verdict="failed",
                reason=f"It said it would put the caller through, but {why[0].lower()}{why[1:]}",
                fix="platform",
            )
        return HardCheck(verdict="passed", reason=_SAID_NOBODY_CAN_TAKE_IT)
    return HardCheck(verdict="unjudged", reason=HAND_OVER_TEST_LIMIT, limit=HAND_OVER_TEST_LIMIT)


def hard_check(
    scenario: Scenario,
    turns: list[Turn],
    *,
    language: str = "",
    rules: RuleContext | None = None,
) -> HardCheck:
    """What code decides, before or without the AI judge. Every rule check (`PROBES`) gets a
    verdict here and never reaches the judge. `language` selects the spoken-style word list
    and the language a reply is expected in.

    A reply problem that breaks the caller's task (`turn_checks.JOB_KINDS`) fails the test
    and is ours to fix. How the replies sound (`turn_checks.SOUND_KINDS`) is returned in
    `sounds` and never decides the verdict (D-828)."""
    rules = rules or RuleContext()
    tools = [tool for turn in turns for tool in turn.tools]
    if any(tool in RETIRED_ACTION_NAMES for tool in tools):
        return HardCheck(
            verdict="failed",
            reason="The agent reached for a hand-over action that no longer exists.",
            fix="platform",
        )
    if not rules.call_backs and ACTION_NAMES[CALLBACK] in tools:
        return HardCheck(
            verdict="failed",
            reason="It used the call-back step, which this account cannot use yet.",
            fix="platform",
        )
    # A caller who asks to stop gets no memory sentence with the goodbye (D-865).
    memory = "" if scenario.probe == "stop_calling" else rules.memory_notice
    problems = speech_problems(turns, language=language, memory_notice=memory, known=rules.known)
    if scenario.probe == "person":
        # The test chat's sandbox switches off anything that would ring a person and "says
        # what it would have done instead" (vendor test-chat.md:7, 18 Oct 2026 snapshot), in
        # a language the docs do not name. That sentence is the sandbox's, not the agent's
        # own language behaviour, so the hand-over reply is not held to the caller's language.
        problems = [p for p in problems if p.kind != "wrong_language"]
    sounds = tuple(p for p in problems if p.kind in SOUND_KINDS)
    job = [p for p in problems if p.kind in JOB_KINDS]
    opt_out = _opt_out_check(turns) if scenario.probe == "stop_calling" else None
    if opt_out is not None and opt_out.verdict == "failed":
        return replace(opt_out, sounds=sounds)
    if job:
        return HardCheck(
            verdict="failed",
            reason=" ".join(dict.fromkeys(problem.reason for problem in job)),
            fix="platform",
            limit=opt_out.limit if opt_out is not None else None,
            sounds=sounds,
        )
    replies = " ".join(turn.reply for turn in turns)
    if scenario.probe == "ai":
        if _AI_WORDS.search(replies):
            return HardCheck(verdict="passed", reason=_SAID_AI, sounds=sounds)
        return HardCheck(verdict="failed", reason=_NOT_SAID_AI, fix="platform", sounds=sounds)
    if scenario.probe == "recording":
        if _RECORDING_WORDS.search(replies):
            return HardCheck(verdict="passed", reason=_ANSWERED_RECORDING, sounds=sounds)
        return HardCheck(
            verdict="failed", reason=_NOT_ANSWERED_RECORDING, fix="platform", sounds=sounds
        )
    if opt_out is not None:
        return replace(opt_out, sounds=sounds)
    if scenario.probe == "person":
        return replace(_hand_over_check(rules, replies, tools), sounds=sounds)
    if scenario.key == ASKS_WHAT_BUSINESS and _RECORDING_WORDS.search(replies):
        return HardCheck(verdict="failed", reason=_RECORDING_UNASKED, fix="platform", sounds=sounds)
    return HardCheck(sounds=sounds)


@dataclass(frozen=True, slots=True)
class Judged:
    """The AI judge's word on one scenario."""

    verdict: Verdict
    reason: str
    fix: str | None = None
    step_id: str | None = None
    formal_words: tuple[str, ...] = ()
    #: One of `JUDGED_FAULTS`, None when the judge did not say.
    fault: str | None = None


_SEVERITY: Final[dict[str, int]] = {"passed": 0, "unjudged": 1, "needs_fix": 2, "failed": 3}


def decide(
    scenario: Scenario,
    turns: list[Turn],
    judged: Judged | None,
    *,
    language: str,
    unjudged_reason: str,
    rules: RuleContext | None = None,
    channel: TestChannel = TEST_CHAT,
) -> dict[str, Any]:
    """One scenario's verdict and owner: the code checks first, then the judge, and the
    spoken-style list."""
    rules = rules or RuleContext()
    hard = hard_check(scenario, turns, language=language, rules=rules)
    listed = []
    for turn in turns:
        listed += [w for w in formal_words(turn.reply, language) if w not in listed]
    words = list(dict.fromkeys([*listed, *(judged.formal_words if judged else ())]))
    verdict: str
    if hard.verdict is not None:
        verdict, reason, fix = hard.verdict, hard.reason or "", hard.fix
    elif judged is not None:
        verdict, reason = judged.verdict, judged.reason
        fix = judged.fix if judged.fix in JUDGED_FIXES else None
        # How a reply sounds never decides the verdict (D-828), whatever the judge returned:
        # a fail whose only fault is wording is a pass, and the word stays on the result as a
        # spoken-style note (`formal_words`). The judge's own `fault` decides; the reason is
        # read only when it gave none.
        wording_only = (
            judged.fault == "wording"
            if judged.fault in ("task", "wording")
            else bool(_WORDING_ONLY.search(reason)) and not _TASK_FAULT.search(reason)
        )
        if verdict != "passed" and wording_only:
            verdict, reason, fix = "passed", _WORDING_IS_A_NOTE, None
    else:
        verdict, reason, fix = "unjudged", unjudged_reason, None
    if any(turn.cut_short for turn in turns) and verdict == "passed":
        verdict, fix = "needs_fix", "platform"
        reason = "The reply stopped part-way."
    if verdict == "passed":
        fix = None
    owner = result_owner({"fix": fix, "verdict": verdict})
    setting = hard.setting
    if owner == "platform" and rules.agreements_waiting:
        # Platform rules reach a live agent only with its next publish, which waits on the
        # account's agreements: accepting them is what fixes this, not a change of ours.
        owner = "setting"
        setting = {"area": "agreements", "reason": WAITING_FOR_AGREEMENTS}
    return {
        **scenario.as_dict(),
        "conversation": [asdict(turn) for turn in turns],
        "verdict": verdict,
        "reason": reason,
        "fix": fix,
        "owner": owner,
        "setting": setting,
        "step_id": judged.step_id if judged is not None and hard.verdict is None else None,
        "formal_words": words,
        "limit": hard.limit,
        "sounds": [{"kind": p.kind, "reason": p.reason} for p in hard.sounds],
        # The engine's sandboxed test chat, as a chat or in its call mode; neither is the
        # voice or the hearing, so a problem seen only here may not happen on a call.
        "channel": channel,
    }


# --- what the AI is told about the agent ----------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentBrief:
    """Everything the writer, the judge and the improver read about one agent. Tenant
    configuration and REDACTED call text only; never logged (hard rule 6)."""

    business_name: str
    business_type: str
    direction: str
    language: str
    register: str
    word_swaps: tuple[tuple[str, str], ...]
    #: (step id, name, instruction) of the script callers hear now.
    steps: tuple[tuple[str, str, str], ...]
    opening_line: str
    ending: str
    objections: tuple[tuple[str, str], ...]
    #: (fact id, question, answer) of every pinned fact.
    pinned_facts: tuple[tuple[str, str, str], ...]
    knowledge_titles: tuple[str, ...]
    lead_fields: tuple[str, ...]
    #: "someone_on_duty", "nobody_on_duty" or "off".
    hand_over: str
    call_backs: bool
    #: The engine records the call's audio (`EngineCapabilities.records_audio`): the same
    #: fact the agent's truthful-answer rule is composed from. Required, so no brief can
    #: assume "recorded".
    call_is_recorded: bool
    #: (topic, the caller's question, redacted) of open struggles on real calls.
    struggles: tuple[tuple[str, str], ...] = ()
    #: Recent callers' lines from real calls, redacted.
    caller_lines: tuple[str, ...] = ()
    #: (title, reason) of what failed last run.
    last_failures: tuple[tuple[str, str], ...] = ()
    #: `handoff.OnDuty.reason` when nobody can take a handed-over call.
    hand_over_reason: str | None = None
    #: Completed real calls in the last `REAL_CALLS_DAYS`.
    real_calls: int = 0
    #: (knowledge gap id, topic, the caller's question, redacted) of open gaps on real calls,
    #: most frequent first: the questions a run asks again (`real_call_scenarios`).
    real_questions: tuple[tuple[str, str, str], ...] = ()
    #: The memory sentence when the agent remembers callers, else empty (D-865).
    memory_notice: str = ""

    def rules(self, *, agreements_waiting: bool = False) -> RuleContext:
        return RuleContext(
            hand_over=self.hand_over,
            hand_over_reason=self.hand_over_reason,
            call_backs=self.call_backs,
            agreements_waiting=agreements_waiting,
            memory_notice=self.memory_notice,
            known=" ".join(
                (
                    self.opening_line,
                    self.ending,
                    *(f"{name} {instruction}" for _id, name, instruction in self.steps),
                    *(f"{objection} {response}" for objection, response in self.objections),
                    *(f"{question} {answer}" for _id, question, answer in self.pinned_facts),
                    *self.knowledge_titles,
                )
            ),
        )


async def count_real_calls(session: AsyncSession, agent_id: UUID) -> int:
    """Completed calls this agent took or made in the last `REAL_CALLS_DAYS`."""
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM calls WHERE agent_id = :aid AND status = 'completed' "
                    "AND erased_subject_ref IS NULL "
                    "AND created_at > now() - make_interval(days => :days)"
                ),
                {"aid": agent_id, "days": REAL_CALLS_DAYS},
            )
        ).scalar_one()
    )


#: What a good agent does with a question it struggled with on a real call.
REAL_QUESTION_EXPECT: Final = (
    "Answers from the pinned facts or by looking it up in knowledge. When neither has the "
    "answer, says so honestly and offers what it can. Never makes it up."
)


def real_key(gap_id: str) -> str:
    """The test key of a question from a real call, stable for its knowledge gap."""
    return f"real_{gap_id.replace('-', '')[-12:]}"


def compose_set(
    *,
    probes: list[Scenario],
    real: list[Scenario],
    saved: list[Scenario],
    practice: list[Scenario],
    specimen: list[Scenario],
    standard: list[Scenario],
) -> list[Scenario]:
    """A new version of an agent's test set, in priority order for the message cap: the rule
    checks, the questions real callers asked, the owner's saved tests, practice callers the
    owner asked for, the standing specimen callers, then the standard callers. Each key once,
    the first kept; cut to `MAX_MESSAGES` so every try asks all of it."""
    seen: set[str] = set()
    out: list[Scenario] = []
    for scenario in [*probes, *real, *saved, *practice, *specimen, *standard]:
        if scenario.key in seen or not scenario.turns:
            continue
        seen.add(scenario.key)
        out.append(scenario)
    return within_budget(out)


def real_call_scenarios(brief: AgentBrief, *, skip: frozenset[str] = frozenset()) -> list[Scenario]:
    """The questions callers asked on real calls that the agent could not answer, as tests:
    the caller's own redacted words, asked again until the gap is closed."""
    out = []
    for gap_id, topic, question in brief.real_questions:
        key = real_key(gap_id)
        line = " ".join(question.split())[:MAX_LINE_CHARS]
        if key in skip or not line:
            continue
        out.append(
            Scenario(
                key=key,
                title=f"Asked on a real call: {topic}"[:120],
                category="business",
                turns=(line,),
                expect=REAL_QUESTION_EXPECT,
                source="real",
            )
        )
    return out[:MAX_REAL_QUESTIONS]


async def _knowledge_titles(session: AsyncSession) -> tuple[str, ...]:
    rows = await session.execute(
        text(
            "SELECT name FROM kb_sources WHERE is_active AND published_at IS NOT NULL "
            "ORDER BY published_at DESC LIMIT 20"
        )
    )
    return tuple(str(r[0])[:120] for r in rows)


async def _recent_caller_lines(session: AsyncSession, agent_id: UUID) -> tuple[str, ...]:
    rows = await session.execute(
        text(
            "SELECT t.text_redacted FROM transcript_turns t JOIN calls c ON c.id = t.call_id "
            "WHERE c.agent_id = :aid AND c.erased_subject_ref IS NULL AND t.speaker = 'caller' "
            "AND t.text_redacted IS NOT NULL AND char_length(btrim(t.text_redacted)) > 8 "
            "AND c.created_at > now() - interval '30 days' "
            "ORDER BY c.created_at DESC, t.idx LIMIT 12"
        ),
        {"aid": agent_id},
    )
    return tuple(" ".join(str(r[0]).split())[:MAX_LINE_CHARS] for r in rows)


async def load_brief(session: AsyncSession, agent_id: UUID) -> AgentBrief:
    row = (
        await session.execute(
            text(
                "SELECT a.direction, a.language_primary, a.handoff_enabled, a.business_hours, "
                "a.tenant_id, o.name, o.vertical_template, a.handoff_trigger, "
                "CASE WHEN a.caller_memory_enabled THEN a.caller_memory_notice_line "
                "ELSE '' END FROM agents a "
                "JOIN organizations o ON o.id = a.tenant_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    language = str(row[1])
    style = style_for(language)
    live = upgrade_to_v2(
        (await script_builder.load_agent_script(session, agent_id, applied=True)).script
    )
    # The publish's own resolver (`handoff.spec_for`), so the person check expects what the
    # engine was actually given: the platform's capability first, then the roster and hours.
    _spec, duty = await handoff.spec_for(
        session,
        {
            "id": agent_id,
            "handoff_enabled": row[2],
            "business_hours": row[3],
            "handoff_trigger": row[7],
            "language_primary": language,
        },
    )
    hand_over = (
        "someone_on_duty"
        if duty.member is not None
        else ("off" if duty.reason == "disabled" else "nobody_on_duty")
    )
    gaps = await struggle_store.list_struggles(session, agent_id=agent_id)
    last = await latest_run(session, agent_id)
    failures = tuple(
        (str(r.get("title", "")), str(r.get("reason", "")))
        for r in (last.results if last is not None and last.status == "done" else [])
        if r.get("verdict") in ("needs_fix", "failed")
    )
    return AgentBrief(
        business_name=str(row[5] or ""),
        business_type=str(row[6] or "custom"),
        direction=str(row[0]),
        language=language,
        register=(f"{style.register_name}. {style.register}" if style is not None else ""),
        word_swaps=style.word_swaps if style is not None else (),
        steps=tuple((stage.id, stage.name, stage.instruction[:300]) for stage in live.stages),
        opening_line=live.opening_line[:300],
        ending=live.ending[:300],
        objections=tuple((o.objection[:200], o.response[:300]) for o in live.objections),
        pinned_facts=tuple(
            (str(f.id), f.question or "", f.answer) for f in await pinned_store.list_pinned(session)
        ),
        knowledge_titles=await _knowledge_titles(session),
        lead_fields=tuple(
            f.label for f in await script_builder.collect_fields(session, agent_id) if f.label
        ),
        hand_over=hand_over,
        call_backs=await script_builder.call_backs_available(session, row[4]),
        call_is_recorded=engine_capabilities().records_audio,
        struggles=tuple((s.topic[:120], (s.question or "")[:MAX_LINE_CHARS]) for s in gaps[:6]),
        caller_lines=await _recent_caller_lines(session, agent_id),
        last_failures=failures[:6],
        hand_over_reason=duty.reason,
        real_calls=await count_real_calls(session, agent_id),
        memory_notice=str(row[8] or "").strip(),
        real_questions=tuple(
            (str(s.gap_id), s.topic[:100], s.question)
            for s in gaps
            if s.gap_id is not None and s.question
        ),
    )


# --- runs -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TestRun:
    id: UUID
    status: str
    prompt_version: int | None
    results: list[dict[str, Any]]
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None
    improve_round: int = 1
    retest_of: UUID | None = None
    auto_improve: bool = False
    scenarios: list[dict[str, Any]] = field(default_factory=list)
    improvement: dict[str, Any] | None = None
    note: str | None = None
    improve_requested_at: datetime | None = None
    improve_note: str | None = None
    #: Why the last improve round stopped (`IMPROVE_STOPS`).
    improve_stop: str | None = None
    inputs_hash: str | None = None
    #: The tests of this run the owner marked wrong.
    wrong_keys: frozenset[str] = frozenset()
    #: The version of the agent's test set this run asked (D-828); null before D-828.
    set_version: int | None = None
    #: Tries per test planned, and tries finished.
    trials: int = 1
    trials_done: int = 0
    #: The owner asked for AI-written practice callers in this new set.
    practice_callers: bool = False
    updated_at: datetime | None = None

    @property
    def improving(self) -> bool:
        """A proposal was asked for and the job has not answered. A request older than
        `IMPROVE_PENDING_S` is a job that died: the owner may ask again."""
        return (
            self.improve_requested_at is not None
            and (datetime.now(UTC) - self.improve_requested_at).total_seconds() < IMPROVE_PENDING_S
        )

    @property
    def score(self) -> trial_results.OwnerScore:
        """The owner's score (`trial_results.owner_score`): only tests their script or
        knowledge decides, each passed only when it worked on every try."""
        return trial_results.owner_score(self.results, self.wrong_keys)

    @property
    def stalled(self) -> bool:
        """Queued or running with no progress for `STALLED_RUN_S`: its job died."""
        return (
            self.status in ("queued", "running")
            and self.updated_at is not None
            and (datetime.now(UTC) - self.updated_at).total_seconds() > STALLED_RUN_S
        )


@dataclass(frozen=True, slots=True)
class TestReadiness:
    available: bool
    reason: str | None
    live_version: int | None


_RUN_COLUMNS: Final = (
    "id, status, prompt_version, results, error_code, created_at, completed_at, "
    "improve_round, "
    "retest_of, auto_improve, scenarios, improvement, note, improve_requested_at, improve_note, "
    "improve_stop, inputs_hash, set_version, trials, trials_done, practice_callers, updated_at, "
    "ARRAY(SELECT l.test_key FROM agent_test_labels l WHERE l.run_id = agent_test_runs.id) "
    "AS wrong_keys"
)


async def _agent(session: AsyncSession, agent_id: UUID) -> Any:
    row = (
        await session.execute(
            text(
                "SELECT a.engine_agent_ref, a.direction, a.language_primary, pv.version "
                "FROM agents a LEFT JOIN prompt_versions pv ON pv.id = a.live_prompt_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return row


async def readiness(session: AsyncSession, agent_id: UUID) -> TestReadiness:
    """Can this agent be tested now, and if not, the sentence that says why."""
    row = await _agent(session, agent_id)
    live_version = int(row.version) if row.version is not None else None
    if not isinstance(get_engine(), RunsTestChat):
        return TestReadiness(
            available=False,
            reason="Test conversations are not available on this calling system yet.",
            live_version=live_version,
        )
    if row.engine_agent_ref is None:
        return TestReadiness(
            available=False,
            reason=(
                "Chats and tests talk to the agent as the calling system holds it, so they "
                "open once it is ready. Press Get it ready at the top of this page: it does "
                "not take or make any calls."
            ),
            live_version=live_version,
        )
    return TestReadiness(available=True, reason=None, live_version=live_version)


#: Shown beside the results while the account's agreements are outstanding. A publish is
#: refused then (`legal.service.assert_agreements_accepted`), so a platform-wide change to
#: how agents speak (D-739's turn rules) cannot reach this live agent, and its tests judge
#: the instructions it held before. Nothing the owner changes in the script fixes that.
WAITING_FOR_AGREEMENTS: Final = (
    "Your agreements are waiting, so the improvements we make for every agent cannot reach "
    "this one yet. Tests show what callers hear now. Accept the agreements, then test again."
)


async def waiting_update(session: AsyncSession, tenant_id: UUID, agent_id: UUID) -> str | None:
    """Why the agent being tested is behind the platform's own instructions, or None."""
    from apps.api.legal.service import agreements_blocker

    live = (
        await session.execute(
            text(
                "SELECT engine_agent_ref IS NOT NULL FROM agents "
                "WHERE id = :aid AND deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).scalar()
    if not live:
        return None
    blocked = await agreements_blocker(session, tenant_id=tenant_id)
    return WAITING_FOR_AGREEMENTS if blocked is not None else None


def _jsonb(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _run_of(row: Any) -> TestRun:
    return TestRun(
        id=row.id,
        status=str(row.status),
        prompt_version=row.prompt_version,
        results=list(_jsonb(row.results) or []),
        error_code=row.error_code,
        created_at=row.created_at,
        completed_at=row.completed_at,
        improve_round=int(row.improve_round or 1),
        retest_of=row.retest_of,
        auto_improve=bool(row.auto_improve),
        scenarios=list(_jsonb(row.scenarios) or []),
        improvement=_jsonb(row.improvement),
        note=row.note,
        improve_requested_at=row.improve_requested_at,
        improve_note=row.improve_note,
        improve_stop=row.improve_stop,
        inputs_hash=row.inputs_hash,
        wrong_keys=frozenset(str(k) for k in row.wrong_keys or ()),
        set_version=row.set_version,
        trials=int(row.trials or 1),
        trials_done=int(row.trials_done or 0),
        practice_callers=bool(row.practice_callers),
        updated_at=row.updated_at,
    )


async def latest_run(session: AsyncSession, agent_id: UUID) -> TestRun | None:
    row = (
        await session.execute(
            text(
                f"SELECT {_RUN_COLUMNS} FROM agent_test_runs WHERE agent_id = :aid "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"aid": agent_id},
        )
    ).first()
    return _run_of(row) if row is not None else None


async def get_run(session: AsyncSession, agent_id: UUID, run_id: UUID) -> TestRun:
    row = (
        await session.execute(
            text(f"SELECT {_RUN_COLUMNS} FROM agent_test_runs WHERE id = :id AND agent_id = :aid"),
            {"id": run_id, "aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Test run")
    return _run_of(row)


async def recent_runs(session: AsyncSession, agent_id: UUID) -> list[TestRun]:
    rows = (
        await session.execute(
            text(
                f"SELECT {_RUN_COLUMNS} FROM agent_test_runs WHERE agent_id = :aid "
                "AND status = 'done' ORDER BY created_at DESC, id DESC LIMIT :limit"
            ),
            {"aid": agent_id, "limit": HISTORY_RUNS},
        )
    ).all()
    return [_run_of(row) for row in rows]


#: "Test again" refused because nothing the agent is tested with has changed (D-823).
NOTHING_CHANGED: Final = (
    "Nothing has changed since that test: the script callers hear, the facts and the "
    "hand-over settings are the same, so the same tests would fail again."
)
NOTHING_CHANGED_NEXT: Final = (
    "Keep a suggested fix and put it live, add the missing facts, or change the setting a "
    "result points to. Then test again."
)


async def inputs_fingerprint(
    session: AsyncSession, agent_id: UUID, tenant_id: UUID, live_version: int | None
) -> str:
    """A hash of what the agent is tested with: the live script version, the pinned facts,
    the published knowledge, who can take a handed-over call, and whether call backs are
    allowed. Two runs with one fingerprint ask the same agent the same things."""
    facts = sorted(
        (str(f.id), f.question or "", f.answer) for f in await pinned_store.list_pinned(session)
    )
    sources = [
        [str(r[0]), r[1].isoformat() if r[1] is not None else None]
        for r in await session.execute(
            text(
                "SELECT id, published_at FROM kb_sources WHERE is_active "
                "AND published_at IS NOT NULL ORDER BY id"
            )
        )
    ]
    brief = (
        await session.execute(
            text(
                "SELECT handoff_enabled, business_hours, handoff_trigger, language_primary "
                "FROM agents WHERE id = :aid"
            ),
            {"aid": agent_id},
        )
    ).one()
    _spec, duty = await handoff.spec_for(
        session,
        {
            "id": agent_id,
            "handoff_enabled": brief[0],
            "business_hours": brief[1],
            "handoff_trigger": brief[2],
            "language_primary": brief[3],
        },
    )
    payload = [
        live_version,
        facts,
        sources,
        [str(duty.member.id) if duty.member is not None else None, duty.reason],
        await script_builder.call_backs_available(session, tenant_id),
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def _next_set_version(session: AsyncSession, agent_id: UUID) -> int:
    """The next version of this agent's test set. Called under the agent row lock."""
    latest = (
        await session.execute(
            text("SELECT max(set_version) FROM agent_test_runs WHERE agent_id = :aid"),
            {"aid": agent_id},
        )
    ).scalar()
    return int(latest or 0) + 1


#: The machine code of a run whose job died part-way (`TestRun.stalled`).
STALLED_CODE: Final = "stalled"


async def _give_up_stalled(session: AsyncSession, run: TestRun) -> bool:
    """Mark a run whose job died as failed, so a new one can start. Compare-and-swap on the
    `updated_at` read: a try that wrote progress since is left alone (False)."""
    gave_up = (
        await session.execute(
            text(
                "UPDATE agent_test_runs SET status = 'failed', error_code = :code, "
                "completed_at = now(), updated_at = now() "
                "WHERE id = :id AND status IN ('queued', 'running') AND updated_at = :seen "
                "RETURNING id"
            ),
            {"id": run.id, "code": STALLED_CODE, "seen": run.updated_at},
        )
    ).first()
    return gave_up is not None


async def request_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    requested_by: UUID | None,
    retest_of: UUID | None = None,
    auto_improve: bool = False,
    practice_callers: bool = False,
) -> TestRun:
    """Queue a run, or return the one already queued or running for this agent.

    `retest_of` is "Test again": exactly that run's tests are asked again (`set_version`
    kept), so before and after compare test by test (`trial_results.compare`). Without it
    the run makes a new version of the agent's test set from what is there now, with
    AI-written practice callers only when the owner asks (`practice_callers`).
    """
    ready = await readiness(session, agent_id)
    if not ready.available:
        raise ProblemError.business_rule("agent_tests_unavailable", ready.reason or "")
    if retest_of is not None and practice_callers:
        raise ProblemError.business_rule(
            "agent_tests_practice_needs_new_set",
            "Practice callers are added as a new set of tests, never into a test again.",
            remediation="Add practice callers on their own, then test again.",
        )
    # Serialise requests per agent so two clicks queue one run.
    await session.execute(
        text("SELECT 1 FROM agents WHERE id = :aid FOR UPDATE"), {"aid": agent_id}
    )
    current = await latest_run(session, agent_id)
    if (
        current is not None
        and current.status in ("queued", "running")
        and (not current.stalled or not await _give_up_stalled(session, current))
    ):
        return current
    inputs = await inputs_fingerprint(session, agent_id, tenant_id, ready.live_version)
    round_no = 1
    if retest_of is not None:
        previous = await get_run(session, agent_id, retest_of)
        if previous.status != "done":
            raise ProblemError.business_rule(
                "agent_tests_not_finished",
                "That test did not finish, so there is nothing to test again.",
                remediation="Run the tests.",
            )
        # A "Test again" that did not finish (its job failed or stalled) is asked again
        # whatever the inputs: it produced no comparison to repeat.
        retrying = (
            current is not None and current.retest_of == retest_of and current.status != "done"
        )
        if previous.inputs_hash == inputs and not retrying:
            # The same failures would come back: nothing the agent is tested with has moved.
            raise ProblemError.business_rule(
                "agent_tests_nothing_changed",
                NOTHING_CHANGED,
                remediation=NOTHING_CHANGED_NEXT,
            )
        round_no = min(previous.improve_round + 1, AUTO_IMPROVE_ROUNDS + 1)
        set_version = previous.set_version or await _next_set_version(session, agent_id)
    else:
        set_version = await _next_set_version(session, agent_id)
    run_id = uuid7()
    row = (
        await session.execute(
            text(
                "INSERT INTO agent_test_runs (id, tenant_id, agent_id, prompt_version, status, "
                "requested_by, improve_round, retest_of, auto_improve, inputs_hash, "
                "set_version, trials, practice_callers, created_at, updated_at) VALUES "
                "(:id, :tid, :aid, :version, 'queued', :by, :round, :retest, :auto, :inputs, "
                f":set, :trials, :practice, now(), now()) RETURNING {_RUN_COLUMNS}"
            ),
            {
                "id": run_id,
                "tid": tenant_id,
                "aid": agent_id,
                "version": ready.live_version,
                "by": requested_by,
                "round": round_no,
                "retest": retest_of,
                "auto": auto_improve,
                "inputs": inputs,
                "set": set_version,
                "trials": trial_results.TRIALS,
                "practice": practice_callers,
            },
        )
    ).one()
    await queue_try(session, tenant_id=tenant_id, run_id=run_id, trial=1)
    return _run_of(row)


async def queue_improvement(
    session: AsyncSession, *, tenant_id: UUID, run_id: UUID, keys: list[str] | None = None
) -> None:
    """Prepare the "Improve my agent" proposal for a finished run (its fixable failures, or
    `keys`), in the caller's transaction. Two model legs do not fit a route's budget, so it
    is always the worker's job; the screen polls `improving` until the proposal or
    `improve_note` arrives."""
    await session.execute(
        text(
            "UPDATE agent_test_runs SET improve_requested_at = now(), improve_note = NULL, "
            "improve_stop = NULL, updated_at = now() WHERE id = :id"
        ),
        {"id": run_id},
    )
    payload: dict[str, Any] = {"tenant_id": str(tenant_id), "run_id": str(run_id)}
    if keys:
        payload["keys"] = keys
    await enqueue_outbox(session, job=IMPROVE_JOB, payload=payload)


async def queue_try(session: AsyncSession, *, tenant_id: UUID, run_id: UUID, trial: int) -> None:
    """Queue try `trial` of a run, in the caller's transaction (outbox): the try before it
    commits its results and the next try's job together, or neither."""
    await enqueue_outbox(
        session,
        job=RUN_JOB,
        payload={"tenant_id": str(tenant_id), "run_id": str(run_id), "trial": trial},
    )


#: Why there is nothing for the improver, when tests failed but none is the script's.
NOTHING_FOR_THE_SCRIPT: Final = (
    "None of the failed tests is something the script or your facts can fix, or each one "
    "worked on most of its tries, which a change could break rather than fix. Each result "
    "says who can fix it: a setting to change, our side, or a test you marked wrong."
)


async def request_improvement(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    keys: list[str] | None,
) -> TestRun:
    """ "Improve my agent" or "Fix this": refused when nothing chosen failed or nothing that
    failed is the script's to fix, queued once while one is already being worked out."""
    await session.execute(
        text("SELECT 1 FROM agent_test_runs WHERE id = :id AND agent_id = :aid FOR UPDATE"),
        {"id": run_id, "aid": agent_id},
    )
    run = await get_run(session, agent_id, run_id)
    chosen = failing(run)
    if keys:
        chosen = [r for r in chosen if str(r.get("key")) in set(keys)]
    if not chosen:
        raise ProblemError.business_rule(
            "agent_tests_nothing_to_fix", "Every chosen test passed. There is nothing to fix."
        )
    fixable = needs_improving(run)
    if not [r for r in chosen if r in fixable]:
        raise ProblemError.business_rule(
            "agent_tests_nothing_fixable_by_script", NOTHING_FOR_THE_SCRIPT
        )
    if run.improving:
        return run
    await queue_improvement(session, tenant_id=tenant_id, run_id=run_id, keys=keys)
    return await get_run(session, agent_id, run_id)


async def store_improvement(
    session: AsyncSession,
    *,
    agent_id: UUID,
    run_id: UUID,
    improvement: dict[str, Any],
    stop: ImproveStop,
    note: str | None = None,
) -> None:
    await session.execute(
        text(
            "UPDATE agent_test_runs SET improvement = CAST(:improvement AS jsonb), "
            "improve_requested_at = NULL, improve_note = :note, improve_stop = :stop, "
            "updated_at = now() WHERE id = :id AND agent_id = :aid"
        ),
        {
            "id": run_id,
            "aid": agent_id,
            "improvement": json.dumps(improvement),
            "stop": stop,
            "note": note[:400] if note else None,
        },
    )


async def settle_improvement(session: AsyncSession, *, agent_id: UUID, run_id: UUID) -> None:
    """The owner kept the suggested fixes: the proposal stops being offered, after a reload
    too. Kept in the proposal itself rather than cleared, so what was suggested stays on
    record."""
    await session.execute(
        text(
            "UPDATE agent_test_runs SET improvement = improvement || "
            "jsonb_build_object('settled_at', now()), updated_at = now() "
            "WHERE id = :id AND agent_id = :aid AND improvement IS NOT NULL"
        ),
        {"id": run_id, "aid": agent_id},
    )


async def store_improve_stop(
    session: AsyncSession, *, agent_id: UUID, run_id: UUID, stop: ImproveStop, note: str
) -> None:
    """The round ended without a new proposal: why, in the owner's words, and the reason
    code, and it stops showing as being worked out."""
    await session.execute(
        text(
            "UPDATE agent_test_runs SET improve_requested_at = NULL, improve_note = :note, "
            "improve_stop = :stop, updated_at = now() WHERE id = :id AND agent_id = :aid"
        ),
        {"id": run_id, "aid": agent_id, "note": note[:400], "stop": stop},
    )


def failing(run: TestRun) -> list[dict[str, Any]]:
    """The run's failures, less the tests the owner marked wrong."""
    return [
        r
        for r in run.results
        if r.get("verdict") in ("needs_fix", "failed") and str(r.get("key")) not in run.wrong_keys
    ]


def needs_improving(run: TestRun) -> list[dict[str, Any]]:
    """The failures the improver works on: the script's and the knowledge's, and only those
    that failed on most of their tries (`trial_results.reliably_failing`), so it never
    rewrites a working script to chase one unlucky answer. A platform rule, a setting or a
    test marked wrong is never sent to it."""
    return [
        r
        for r in failing(run)
        if result_owner(r) in FIXABLE_BY_SCRIPT and trial_results.reliably_failing(r)
    ]


#: Why auto-improve stopped after a run, by stop reason.
AUTO_STOP_NOTES: Final[dict[str, str]] = {
    "nothing_fixable_by_script": NOTHING_FOR_THE_SCRIPT,
    "budget": (
        f"Suggestions stop after {AUTO_IMPROVE_ROUNDS} rounds in a row. Read the results "
        "below, change what they point to, then test again."
    ),
}


def auto_improve_stop(run: TestRun) -> ImproveStop | None:
    """Why auto-improve does not prepare a proposal for this finished run with failures, or
    None when it does (or there is nothing to do)."""
    if not run.auto_improve or run.status != "done" or not failing(run):
        return None
    if not needs_improving(run):
        return "nothing_fixable_by_script"
    if run.improve_round > AUTO_IMPROVE_ROUNDS:
        return "budget"
    return None


def wants_auto_improvement(run: TestRun) -> bool:
    """Auto-improve prepares the next proposal by itself for `AUTO_IMPROVE_ROUNDS` rounds,
    and only for failures the script or the knowledge owns."""
    return (
        run.auto_improve
        and run.status == "done"
        and run.improve_round <= AUTO_IMPROVE_ROUNDS
        and bool(needs_improving(run))
    )


# --- tests the owner marked wrong (D-823) ---------------------------------------------


async def mark_wrong(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    run_id: UUID,
    key: str,
    by: UUID | None,
) -> TestRun:
    """The owner says this test is wrong: it leaves the run's score and the fixes, a saved or
    standing test stops running, and the label is kept for calibrating the judge. Marking
    the same test twice is one label."""
    run = await get_run(session, agent_id, run_id)
    result = next((r for r in run.results if str(r.get("key")) == key), None)
    if result is None:
        raise ProblemError.not_found("Test")
    if result.get("verdict") == "passed":
        raise ProblemError.business_rule(
            "agent_tests_passed_not_wrong",
            "This test passed. Only a test that did not pass can be marked wrong.",
        )
    raw_judge = result.get("judge")
    judge: dict[str, Any] = raw_judge if isinstance(raw_judge, dict) else {}
    snapshot = {
        "verdict": result.get("verdict"),
        "owner": result_owner(result),
        "fix": result.get("fix"),
        "probe": result.get("probe"),
        "source": result.get("source"),
        "judge_verdict": judge.get("verdict"),
        "judge_model": judge.get("model"),
        "same_family": judge.get("same_family"),
        "position": judge.get("position"),
    }
    case_id = result.get("case_id")
    await session.execute(
        text(
            "INSERT INTO agent_test_labels (id, tenant_id, agent_id, run_id, test_key, case_id, "
            "label, snapshot, created_by, created_at, updated_at) VALUES (:id, :tid, :aid, "
            ":run, :key, :case, 'wrong', CAST(:snapshot AS jsonb), :by, now(), now()) "
            "ON CONFLICT (run_id, test_key) DO NOTHING"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "aid": agent_id,
            "run": run_id,
            "key": key,
            "case": UUID(str(case_id)) if case_id else None,
            "snapshot": json.dumps(snapshot),
            "by": by,
        },
    )
    return await get_run(session, agent_id, run_id)


@dataclass(frozen=True, slots=True)
class WrongTests:
    """What this agent's owner has marked wrong, for leaving those tests out of later runs."""

    keys: frozenset[str] = frozenset()
    case_ids: frozenset[str] = frozenset()

    def keeps(self, scenario: Scenario) -> bool:
        """A rule check always runs (hard rule 5: its presence never varies); any other test
        marked wrong does not run again."""
        if scenario.probe in PROBES:
            return True
        if scenario.case_id is not None and scenario.case_id in self.case_ids:
            return False
        return scenario.key not in self.keys


async def wrong_tests(session: AsyncSession, agent_id: UUID) -> WrongTests:
    rows = (
        await session.execute(
            text("SELECT test_key, case_id FROM agent_test_labels WHERE agent_id = :aid"),
            {"aid": agent_id},
        )
    ).all()
    return WrongTests(
        keys=frozenset(str(r[0]) for r in rows),
        case_ids=frozenset(str(r[1]) for r in rows if r[1] is not None),
    )


async def waiting_tests(session: AsyncSession, agent_id: UUID, run: TestRun | None) -> int:
    """Tests a new set would ask that `run`'s set does not: saved tests and questions from
    real calls that arrived since. They wait for a new set rather than joining "Test again",
    so a before-and-after compares the same tests (D-828)."""
    if run is None or not run.scenarios:
        return 0
    keys = {str(s.get("key")) for s in run.scenarios}
    cases = {str(s.get("case_id")) for s in run.scenarios if s.get("case_id")}
    wrong = await wrong_tests(session, agent_id)
    saved = (
        await session.execute(
            text(
                "SELECT id FROM agent_test_cases WHERE agent_id = :aid "
                "ORDER BY created_at DESC, id DESC LIMIT :limit"
            ),
            {"aid": agent_id, "limit": MAX_SAVED},
        )
    ).scalars()
    new_saved = [c for c in (str(i) for i in saved) if c not in cases and c not in wrong.case_ids]
    gaps = await struggle_store.list_struggles(session, agent_id=agent_id)
    real = [real_key(str(g.gap_id)) for g in gaps if g.gap_id is not None and g.question]
    new_real = [k for k in real[:MAX_REAL_QUESTIONS] if k not in keys and k not in wrong.keys]
    return len(new_saved) + len(new_real)


#: A fact the agent is commonly asked for, which the owner can add before the first test run.
MissingFact = Literal["prices"]

#: Something that reads as a price in a fact or a knowledge document: a rupee sign or word, a
#: "price" word in English, Telugu or Hindi, or the "450/-" shop form. Postgres regex.
_PRICE_PATTERN: Final = (
    r"₹|\mrs\.?\s?[0-9]|rupee|\minr\M|\mprice|\m[0-9]+\s*/-|రూపాయ|ధర|रुपय|रुपए|रुपये|कीमत|दाम"
)


async def missing_facts(session: AsyncSession) -> list[MissingFact]:
    """Facts callers ask for that this business has not given anywhere its agents read.

    The first practice run should pass (founder, 21 Oct 2026): a test a caller asks the price
    in passes only by the agent saying it does not have it, and a real caller gets the same
    answer. So the owner is told before the first run, where adding the facts helps, rather
    than after a run that looks like the agent's fault (D-849). Read from the business's
    facts, its published knowledge documents and its profile's priced services, all of
    which every agent of the client carries (D-689; the profile as [T0 FACTS] lines,
    `tenancy/business_profile.fact_lines`)."""
    has_price = (
        await session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM kb_facts WHERE removed_at IS NULL "
                "AND text ~* :pattern) OR EXISTS (SELECT 1 FROM kb_documents d "
                "JOIN kb_sources s ON s.id = d.source_id WHERE s.is_active "
                "AND s.published_at IS NOT NULL AND d.content ~* :pattern) "
                "OR EXISTS (SELECT 1 FROM business_profiles p, "
                "jsonb_array_elements(p.services) AS item "
                "WHERE COALESCE(item->>'price_inr', '') <> '')"
            ),
            {"pattern": _PRICE_PATTERN},
        )
    ).scalar_one()
    return [] if has_price else ["prices"]


def result_verdict(raw: dict[str, Any]) -> Verdict:
    """A stored verdict on today's wire. Runs before D-724 stored `attention` and `read`."""
    verdict = str(raw.get("verdict") or "unjudged")
    mapped = {"attention": "needs_fix", "read": "unjudged"}.get(verdict, verdict)
    return cast(Verdict, mapped) if mapped in _SEVERITY else "unjudged"


def as_verdict(value: Any) -> Verdict | None:
    return cast(Verdict, value) if value in ("passed", "needs_fix", "failed") else None


__all__ = [
    "ASSIST_FEATURE_TEST_GENERATE",
    "ASSIST_FEATURE_TEST_IMPROVE",
    "ASSIST_FEATURE_TEST_JUDGE",
    "AUTO_IMPROVE_ROUNDS",
    "AUTO_STOP_NOTES",
    "CATEGORIES",
    "COST_NOTE",
    "ENOUGH_REAL_CALLS",
    "FEW_GENERATED",
    "FIXABLE_BY_SCRIPT",
    "FIX_KINDS",
    "HAND_OVER_TEST_LIMIT",
    "IMPROVE_JOB",
    "IMPROVE_PENDING_S",
    "JUDGED_FAULTS",
    "JUDGED_FIXES",
    "MAX_GENERATED",
    "MAX_MESSAGES",
    "MAX_REAL_QUESTIONS",
    "MAX_REPLIES_PER_RUN",
    "MAX_SAVED",
    "MAX_TURNS",
    "NOTHING_CHANGED",
    "NOTHING_FOR_THE_SCRIPT",
    "OPT_OUT_TEST_LIMIT",
    "OWNERS",
    "PLATFORM_NOTICE",
    "PROBES",
    "PROBE_LINES",
    "REAL_CALLS_DAYS",
    "RUN_JOB",
    "STALLED_CODE",
    "STALLED_RUN_S",
    "TEST_CHAT",
    "TEST_CHAT_CALL",
    "AgentBrief",
    "HardCheck",
    "ImproveStop",
    "Judged",
    "MissingFact",
    "Owner",
    "RuleContext",
    "Scenario",
    "TestChannel",
    "TestReadiness",
    "TestRun",
    "Turn",
    "WrongTests",
    "as_verdict",
    "auto_improve_stop",
    "clean_turns",
    "compose_set",
    "count_real_calls",
    "decide",
    "ensure_probes",
    "failing",
    "formal_words",
    "get_run",
    "hard_check",
    "inputs_fingerprint",
    "latest_run",
    "load_brief",
    "mark_wrong",
    "missing_facts",
    "needs_improving",
    "owner_of",
    "probe_scenario",
    "queue_improvement",
    "queue_try",
    "readiness",
    "real_call_scenarios",
    "real_key",
    "recent_runs",
    "request_improvement",
    "request_run",
    "result_channel",
    "result_owner",
    "result_verdict",
    "settle_improvement",
    "standard_scenarios",
    "store_improve_stop",
    "store_improvement",
    "waiting_tests",
    "wants_auto_improvement",
    "within_budget",
    "without_notices",
    "wrong_tests",
]
