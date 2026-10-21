"""The Telugu register chat eval (`scripts/register_chat_eval.py`, D-837), run offline.

A fake engine stands in for ThinnestAI at the one seam the eval talks through, so what is
proven is the variants' prompts, the scoring, the clean-up and the spend guard; a variant's
real rate comes only from an operator run.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources

import httpx
import pytest
from apps.api.engine.test_chat import TestChatTurn as ChatTurn
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from calevate_shared import engine
from calevate_shared.call_script import EXAMPLE_HEADER
from calevate_shared.engine import (
    CONFIDENTIALITY_MARKER,
    CONFIDENTIALITY_RULE,
    TRUTHFUL_ANSWER_MARKER,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    EngineAgentRef,
    KBSourceRef,
    compose_engine_prompt,
    truthful_answer_directive,
)
from calevate_shared.spoken_style import style_for
from scripts import register_chat_eval as chat_eval
from scripts import register_eval

TE = register_eval.reference_agent("te-IN", register_eval.load_fixture())
SOURCE = chat_eval.Source(
    agent_id="00000000-0000-0000-0000-000000000001",
    config=TE.model_copy(
        update={"engine_own_voice_key": True, "engine_own_model": "gemini-3.1-flash-lite"}
    ),
    facts="[T0 FACTS]\n- Open 9 to 6",
)
ALL = list(chat_eval.VARIANTS.values())


def _te_data() -> dict[str, object]:
    raw = json.loads(
        resources.files("calevate_shared").joinpath("spoken_style.json").read_text("utf-8")
    )
    te: dict[str, object] = raw["languages"]["te-IN"]
    return te


def _lines_of(block: object) -> set[str]:
    """Every string inside `block`, however nested."""
    if isinstance(block, str):
        return {block}
    if isinstance(block, dict):
        return set().union(*(_lines_of(v) for v in block.values())) if block else set()
    if isinstance(block, list):
        return set().union(*(_lines_of(v) for v in block)) if block else set()
    return set()


# --- variants -------------------------------------------------------------------------------


def test_a_is_the_production_prompt() -> None:
    assert chat_eval.variant_instructions(TE, chat_eval.VARIANTS["A"]) == compose_engine_prompt(TE)


@pytest.mark.parametrize("variant", ALL, ids=lambda v: v.key)
def test_every_variant_keeps_the_truthful_answers_and_confidentiality(
    variant: chat_eval.Variant,
) -> None:
    for cfg in (TE, TE.model_copy(update={"call_is_recorded": False})):
        text = chat_eval.variant_instructions(cfg, variant)
        assert CONFIDENTIALITY_RULE in text
        assert CONFIDENTIALITY_MARKER in text
        assert TRUTHFUL_ANSWER_MARKER in text
        assert text.endswith(truthful_answer_directive(call_is_recorded=cfg.call_is_recorded))


def test_the_ban_bullet_the_variants_edit_is_the_shipped_one() -> None:
    assert any(
        line.startswith(chat_eval.BAN_BULLET_START) for line in VOICE_STYLE_GUIDANCE.splitlines()
    )


@pytest.mark.parametrize("key", ["B", "E"])
def test_no_ban_variants_name_no_word_to_avoid(key: str) -> None:
    style = style_for("te-IN")
    assert style is not None and style.prompt_swaps
    for cfg in (
        TE,
        register_eval.reference_agent("te-IN", register_eval.load_fixture(), ("hi-IN",)),
    ):
        a = chat_eval.variant_instructions(cfg, chat_eval.VARIANTS["A"])
        text = chat_eval.variant_instructions(cfg, chat_eval.VARIANTS[key])
        assert "Spoken words:" in a and "Spoken words:" not in text
        assert "formal or written-style words" in a
        assert "formal or written-style words" not in text
        assert chat_eval.NO_BAN_BULLET in text
        platform = text.split(engine.CLIENT_SCRIPT_OPEN)[0]
        for formal, _spoken in style.prompt_swaps:
            assert f'"{formal}"' not in platform
        # The register line and its fillers stay.
        assert style.register in text
        assert "Fillers, lightly:" in text


def test_the_allow_list_is_the_spoken_side_of_the_word_list() -> None:
    style = style_for("te-IN")
    assert style is not None
    english, native = chat_eval.allow_words("te-IN")
    spoken = [s for _f, s in style.word_swaps if not s.startswith("(")]
    assert english and native
    assert all(any(word in s for s in spoken) for word in english)
    assert all(word in spoken for word in native)
    assert "details" in english and "price" in english and "thanks" in english
    assert not any(word.startswith("(") or "leave it out" in word for word in english + native)
    formal = {f for f, _s in style.word_swaps}
    assert not formal & set(native)


@pytest.mark.parametrize("key", ["C", "E"])
def test_the_allow_list_variants_carry_one_positive_line(key: str) -> None:
    text = chat_eval.variant_instructions(TE, chat_eval.VARIANTS[key])
    assert text.count(chat_eval.allow_line()) == 1
    register = text.split("--- SPOKEN REGISTER ---", 1)[1].split("--- BUSINESS FACTS ---")[0]
    assert chat_eval.allow_line() in register


def test_every_drafted_line_comes_from_the_spoken_style_file() -> None:
    known = _lines_of(_te_data())
    drafted = [text for call in chat_eval.EXAMPLE_CALLS for _who, text in call]
    extra = [line for _key, turns in chat_eval.EXTRA_CONVERSATIONS for line in turns]
    assert set(drafted) <= known
    assert set(extra) <= known
    practised = {line for _key, turns in chat_eval.conversations() for line in turns}
    assert not set(drafted) & practised


@pytest.mark.parametrize("key", ["D", "E"])
def test_the_example_variants_replace_the_scripts_example_call(key: str) -> None:
    assert engine.CLIENT_SCRIPT_OPEN in compose_engine_prompt(TE)
    base_script = TE.system_prompt
    text = chat_eval.variant_instructions(TE, chat_eval.VARIANTS[key])
    assert text.count(EXAMPLE_HEADER) == 1
    for call in chat_eval.EXAMPLE_CALLS:
        for who, said in call:
            assert f"{'Caller' if who == 'caller' else 'You'}: {said}" in text
    fence = text.split(engine.CLIENT_SCRIPT_OPEN, 1)[1].split(engine.CLIENT_SCRIPT_CLOSE)[0]
    assert chat_eval.EXAMPLE_LEAD in fence
    assert EXAMPLE_HEADER in base_script
    replaced = base_script.split(EXAMPLE_HEADER, 1)[1].splitlines()[1:]
    ours = chat_eval.with_example_calls("").splitlines()
    old = [line for line in replaced if line.startswith(("Caller:", "You:")) and line not in ours]
    assert old
    assert not [line for line in old if line in fence.splitlines()]


def test_an_example_call_section_is_added_last_when_the_script_has_none() -> None:
    body = "[BUSINESS]\nA shop.\n\n[ENDING]\nSay bye."
    out = chat_eval.with_example_calls(body)
    assert out.startswith(body)
    assert out.splitlines()[body.count("\n") + 2] == chat_eval.EXAMPLE_LEAD


def test_an_example_call_in_the_middle_keeps_the_sections_after_it() -> None:
    body = "[BUSINESS]\nA shop.\n\n[EXAMPLE CALL] Copy.\nCaller: x\nYou: y\n\n[ENDING]\nSay bye."
    out = chat_eval.with_example_calls(body)
    assert "Caller: x" not in out and "You: y" not in out
    assert out.endswith("[ENDING]\nSay bye.")
    assert out.count(EXAMPLE_HEADER) == 1


def test_the_dry_run_diff_withholds_the_owners_lines() -> None:
    a = chat_eval.variant_instructions(TE, chat_eval.VARIANTS["A"])
    d = chat_eval.variant_instructions(TE, chat_eval.VARIANTS["D"])
    owners = chat_eval.client_script_lines(a)
    diff = chat_eval.variant_diff(a, d)
    assert not any(line[2:] in owners for line in diff if line.startswith("- "))
    report = chat_eval.dry_run_report(SOURCE, ALL)
    assert "MISSING" not in report and "OVER THE LIMIT" not in report


def test_variants_parse_with_a_first() -> None:
    assert [v.key for v in chat_eval.parse_variants("c,b")] == ["A", "C", "B"]
    assert [v.key for v in chat_eval.parse_variants("A,A")] == ["A"]
    with pytest.raises(ValueError, match="unknown variant"):
        chat_eval.parse_variants("A,Z")


def test_the_eval_adapter_composes_instructions_with_what_it_is_given() -> None:
    cfg = SOURCE.config
    compose = chat_eval.instructions_by_copy([chat_eval.VARIANTS["B"]], "run1")
    adapter = chat_eval.VariantThinnestEngine(api_key="test", compose=compose)
    copy = chat_eval.eval_config(cfg, chat_eval.VARIANTS["B"], "run1")
    body = adapter._agent_body(copy)
    assert body["instructions"] == chat_eval.variant_instructions(copy, chat_eval.VARIANTS["B"])
    assert body["byok"] == "llm_voice"
    assert body["name"].startswith(f"{chat_eval.EVAL_PREFIX} B run1")
    # Any other agent, and the default adapter, compose as production does.
    assert adapter._agent_body(cfg)["instructions"] == compose_engine_prompt(cfg)
    assert ThinnestEngine(api_key="t")._agent_body(cfg)["instructions"] == compose_engine_prompt(
        cfg
    )
    others = {k: v for k, v in body.items() if k not in ("instructions", "name")}
    plain = ThinnestEngine(api_key="t")._agent_body(copy)
    assert others == {k: v for k, v in plain.items() if k not in ("instructions", "name")}


def test_a_copy_is_its_own_agent_in_the_developer_workspace() -> None:
    copy = chat_eval.eval_config(
        SOURCE.config.model_copy(
            update={"engine_workspace": "org_client", "has_phone_number": True}
        ),
        chat_eval.VARIANTS["C"],
        "abcd1234",
    )
    assert copy.engine_workspace is None and not copy.has_phone_number
    assert copy.handoff is None and copy.action_tools == ()
    assert copy.tenant_id == chat_eval.EVAL_TENANT
    assert copy.system_prompt == SOURCE.config.system_prompt


def test_a_source_that_cannot_be_measured_is_refused() -> None:
    assert chat_eval.refusal(SOURCE.config) is None
    hindi = SOURCE.config.model_copy(update={"language_primary": "hi-IN"})
    assert "main language" in (chat_eval.refusal(hindi) or "")
    theirs = SOURCE.config.model_copy(update={"engine_own_model": None})
    assert "own model" in (chat_eval.refusal(theirs) or "")


# --- scoring --------------------------------------------------------------------------------


def test_wilson_matches_the_published_formula() -> None:
    # 10 of 20 at 95%: [0.2993, 0.7007] (Wilson 1927; Newcombe 1998 table I method 3).
    low, high = chat_eval.wilson(10, 20)
    assert low == pytest.approx(0.2993, abs=1e-4)
    assert high == pytest.approx(0.7007, abs=1e-4)
    low, high = chat_eval.wilson(0, 60)
    assert low == 0.0 and high == pytest.approx(0.0602, abs=1e-4)
    assert chat_eval.wilson(0, 0) == (0.0, 1.0)


def test_scoring_counts_replies_words_and_failures() -> None:
    r = chat_eval.Reply
    got = [
        r("A", "x", 0, words=("మరియు", "వివరాలు")),
        r("A", "x", 1),
        r("A", "x", 2, error="engine_rate_limited"),
        r("A", "y", 0, words=("మరియు",), cut_short=True),
        r("B", "x", 0, empty=True),
    ]
    t = chat_eval.tally(got)
    assert (t["A"].replies, t["A"].errors, t["A"].with_textbook) == (3, 1, 2)
    assert t["A"].textbook_words == 3 and t["A"].per_reply == pytest.approx(1.0)
    assert t["A"].words == {"మరియు": 2, "వివరాలు": 1}
    assert t["A"].cut_short == 1 and t["B"].empty == 1


def test_a_variant_wins_only_when_its_interval_clears_the_baselines() -> None:
    base = chat_eval.Tally(replies=60, with_textbook=30)
    assert chat_eval.wins(base, chat_eval.Tally(replies=60, with_textbook=10))
    assert not chat_eval.wins(base, chat_eval.Tally(replies=60, with_textbook=22))
    assert not chat_eval.wins(base, chat_eval.Tally())


# --- running against a fake engine ----------------------------------------------------------


class FakeVendor:
    def __init__(self, *, fail_chat_after: int | None = None) -> None:
        self.created: list[AgentConfig] = []
        self.deleted: list[str] = []
        self.knowledge: list[tuple[str, KBSourceRef]] = []
        self.chats = 0
        self.fail_chat_after = fail_chat_after
        self.in_scope = False
        self.created_in_scope: list[bool] = []

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        self.created.append(cfg)
        self.created_in_scope.append(self.in_scope)
        return f"agt_{len(self.created)}"

    async def attach_kb(
        self, ref: EngineAgentRef, source: KBSourceRef, *, agent: AgentConfig | None = None
    ) -> str:
        self.knowledge.append((ref, source))
        return f"kb_{ref}"

    async def test_chat(
        self,
        ref: EngineAgentRef,
        message: str,
        *,
        session: str | None = None,
        call_mode: bool = False,
    ) -> ChatTurn:
        self.chats += 1
        if self.fail_chat_after is not None and self.chats > self.fail_chat_after:
            raise RuntimeError("vendor down")
        reply = "సరే అండి, మరియు వివరాలు చెప్తాను." if ref == "agt_1" else "సరే అండి."
        return ChatTurn(session=session or f"s_{ref}", reply=reply, tools=())

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        self.deleted.append(ref)


async def _no_pause() -> None:
    return None


def _quiet(_line: str) -> None:
    return None


async def test_a_run_creates_talks_and_deletes_every_copy() -> None:
    vendor = FakeVendor()

    @contextmanager
    def scope() -> Iterator[None]:
        vendor.in_scope = True
        try:
            yield
        finally:
            vendor.in_scope = False

    record = await chat_eval.evaluate(
        vendor,
        SOURCE,
        [chat_eval.VARIANTS["A"], chat_eval.VARIANTS["B"]],
        replies=7,
        run_tag="t1",
        pause=_no_pause,
        create_scope=scope,
        say=_quiet,
    )
    assert [c.agent_id for c in vendor.created] == ["t1-A", "t1-B"]
    assert vendor.created_in_scope == [True, True]
    assert sorted(vendor.deleted) == ["agt_1", "agt_2"]
    assert [ref for ref, _s in vendor.knowledge] == ["agt_1", "agt_2"]
    assert all(s.text == SOURCE.facts for _r, s in vendor.knowledge)
    assert record["tally"]["A"]["replies"] == 7 and record["tally"]["B"]["replies"] == 7
    assert record["tally"]["A"]["with_textbook"] == 7
    assert record["tally"]["B"]["with_textbook"] == 0
    assert record["tally"]["A"]["words"] == {"మరియు": 7, "వివరాలు": 7}
    assert record["not_deleted"] == []
    assert record["estimated_inr"] == "0.28"
    rendered = chat_eval.render(record)
    assert "B no ban lists" in rendered and "WINS" in rendered
    # Counts and list words only: no reply text reaches the record.
    assert "చెప్తాను" not in json.dumps(record, ensure_ascii=False)


async def test_a_failed_reply_is_counted_and_the_run_still_ends() -> None:
    vendor = FakeVendor(fail_chat_after=3)
    record = await chat_eval.evaluate(
        vendor,
        SOURCE,
        [chat_eval.VARIANTS["A"]],
        replies=5,
        run_tag="t2",
        pause=_no_pause,
        say=_quiet,
    )
    t = record["tally"]["A"]
    assert t["replies"] == 3 and t["errors"] == 2
    assert vendor.deleted == ["agt_1"]


async def test_the_copies_are_deleted_when_the_run_fails() -> None:
    vendor = FakeVendor()

    async def broken_attach(*_a: object, **_k: object) -> str:
        if len(vendor.created) == 2:
            raise RuntimeError("knowledge refused")
        return "kb"

    vendor.attach_kb = broken_attach  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="knowledge refused"):
        await chat_eval.evaluate(
            vendor, SOURCE, ALL, replies=3, run_tag="t3", pause=_no_pause, say=_quiet
        )
    assert vendor.deleted == ["agt_1", "agt_2"]


async def test_cleanup_deletes_only_our_tagged_eval_agents() -> None:
    seen: list[tuple[str, str]] = []
    rows = [
        {"id": "a1", "name": "TELUGUEVAL B 1a2b3c4d #cv-0123456789ab"},
        {"id": "a2", "name": "Raghava receptionist #cv-0123456789ab"},
        {"id": "a3", "name": "TELUGUEVAL by hand"},
    ]

    def vendor(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        assert "Thinnest-Workspace" not in request.headers
        return httpx.Response(200, json={"items": rows, "nextCursor": None})

    adapter = ThinnestEngine(
        api_key=None,
        client=httpx.AsyncClient(transport=httpx.MockTransport(vendor), base_url=BASE_URL),
    )
    assert await adapter.developer_agents_named(chat_eval.EVAL_PREFIX) == ["a1"]
    with pytest.raises(ValueError, match="prefix"):
        await adapter.developer_agents_named("")


# --- the spend guard ------------------------------------------------------------------------


def test_it_refuses_without_spend(capsys: pytest.CaptureFixture[str]) -> None:
    code = chat_eval.main(["--agent", SOURCE.agent_id, "--variants", "A,B", "--replies", "10"])
    out = capsys.readouterr().out
    assert code == chat_eval.CANNOT_RUN
    assert "20 test-chat replies" in out and "₹0.40" in out
    assert "add --spend" in out


def test_it_refuses_an_unknown_variant_or_no_agent(capsys: pytest.CaptureFixture[str]) -> None:
    assert chat_eval.main(["--agent", SOURCE.agent_id, "--variants", "Q"]) == chat_eval.CANNOT_RUN
    assert chat_eval.main(["--spend"]) == chat_eval.CANNOT_RUN
    assert "unknown variant" in capsys.readouterr().out
