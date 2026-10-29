"""The promo lint and the call-purpose table (D-943): pure, no database.

Each promotional case names the word that must be found; each false-positive guard is a
sentence a real business says on a service call and that must come back `clear`.
"""

from __future__ import annotations

import pytest
from apps.api.compliance.call_purpose import (
    MAX_FINDINGS,
    ScriptPart,
    campaign_purpose,
    first_finding,
    lead_source_purpose,
    lint,
    script_parts,
)
from calevate_shared.call_script import CallScript, FaqEntry


def _verdict(wording: str, kind: str = "instruction") -> str:
    return lint([ScriptPart("Test", wording, kind)]).verdict  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("wording", "category"),
    [
        ("Get 20% off on all services this festive season.", "discount"),
        ("We have a special Diwali offer on 2BHK flats.", "discount"),
        ("Flat 10% cashback if you pay today.", "discount"),
        ("Use promo code SAVE50 at the counter.", "discount"),
        ("This is a limited period offer, so hurry up.", "urgency"),
        ("Don't miss our festive offer.", "urgency"),
        ("Book now and get a free gift.", "urgency"),
        ("Buy now before stocks run out.", "buy_now"),
        ("Rs 500 off on your next order.", "discount"),
        ("₹500 off on your next order.", "discount"),
        # Telugu
        ("ఈ నెల మా దగ్గర డిస్కౌంట్ ఉంది.", "discount"),
        ("దీపావళి ఆఫర్‌లు మొదలయ్యాయి.", "discount"),
        ("ఇది పరిమిత కాలం మాత్రమే, త్వరపడండి.", "urgency"),
        ("offer undi andi, ee roju book cheyandi", "discount"),
        # Hindi
        ("दिवाली पर 10% छूट मिल रही है।", "discount"),
        ("हमारा नया ऑफर सिर्फ आज के लिए है।", "discount"),
        ("जल्दी करें, आखिरी मौका।", "urgency"),
        ("abhi kharidein aur bachat karein", "buy_now"),
    ],
)
def test_promotional_wording_is_found(wording: str, category: str) -> None:
    report = lint([ScriptPart("Opening line", wording, "opening")])
    assert report.verdict == "promotional", wording
    assert category in {finding.category for finding in report.findings}, report.findings
    assert report.blocks_launch


@pytest.mark.parametrize(
    "wording",
    [
        "We have free parking at the back of the clinic.",
        "Please feel free to call us back on this number.",
        "Our toll-free number is on the website.",
        "Are you free tomorrow at five for the appointment?",
        "We offer X-ray, ECG and blood tests at the main branch.",
        "Our after-sales service team will visit on Monday.",
        "You enquired about the flats for sale in Kondapur.",
        "Your order has been shipped and will arrive on Friday.",
        "We do not give any discounts on consultation.",
        "There is no hurry, take your time.",
        "Your appointment is confirmed for 10 am.",
        # Telugu
        "మా క్లినిక్‌లో ఉచిత పార్కింగ్ ఉంది.",
        "రేపు మీరు ఫ్రీగా ఉన్నారా?",
        "కన్సల్టేషన్ మీద డిస్కౌంట్ లేదు.",
        "మీ అపాయింట్‌మెంట్ రేపు ఉదయం పది గంటలకు.",
        # Hindi
        "आपकी कॉल छूट गई थी, इसलिए हम वापस कॉल कर रहे हैं।",
        "फीस पर कोई छूट नहीं है।",
        "क्या आप कल फ्री हैं?",
        "मुफ्त पार्किंग उपलब्ध है।",
    ],
)
def test_everyday_wording_is_not_promotional(wording: str) -> None:
    assert _verdict(wording) == "clear", lint([ScriptPart("Test", wording)]).findings


@pytest.mark.parametrize(
    ("wording", "phrase", "severity"),
    [
        # The script lint's own cases (D-945), now read through this checker.
        ("Book today, special offer for you!", "special offer", "strong"),
        ("ఈ వారం డిస్కౌంట్ ఉంది అండి", "డిస్కౌంట్", "strong"),
        ("अभी कैशबैक मिलेगा", "कैशबैक", "strong"),
        ("Hi, I'm Priya. Limited offer today, shall we talk?", "Limited offer", "strong"),
        ("Only the last few flats are left.", "last few flats", "strong"),
        ("Hurry, only today!", "Hurry", "strong"),
        ("I will send it on WhatsApp, best price!", "best price", "soft"),
        ("It gives guaranteed returns.", "guaranteed returns", "soft"),
        ("ఇది బెస్ట్ ప్రైస్ అండి", "బెస్ట్ ప్రైస్", "soft"),
        ("यह बेस्ट प्राइस है", "बेस्ट प्राइस", "soft"),
    ],
)
def test_first_finding_names_the_first_wording_in_one_line(
    wording: str, phrase: str, severity: str
) -> None:
    found = first_finding(wording)
    assert found is not None, wording
    assert (found.phrase, found.severity) == (phrase, severity)


@pytest.mark.parametrize(
    "wording", ["There is free parking.", "We offer home delivery.", "It is open now."]
)
def test_first_finding_leaves_an_ordinary_fact_alone(wording: str) -> None:
    assert first_finding(wording) is None


def test_soft_wording_asks_for_a_check_and_never_blocks() -> None:
    report = lint([ScriptPart("Step 1", "Tell them about the free consultation.")])
    assert report.verdict == "check"
    assert not report.blocks_launch
    assert report.findings[0].category == "free_offer"


def test_an_answer_given_only_when_asked_is_softened() -> None:
    """A FAQ answer is said when a caller asks; it is their question, not our pitch."""
    report = lint([ScriptPart("Answer", "Seniors get a 10% discount.", "answer")])
    assert report.verdict == "check"
    assert report.findings[0].severity == "soft"


def test_strong_findings_come_first_and_are_capped() -> None:
    wording = " ".join(["Free consultation."] + ["Get 20% off today."] * (MAX_FINDINGS + 5))
    report = lint([ScriptPart("Instructions", wording)])
    assert report.findings[0].severity == "strong"
    assert len(report.findings) <= MAX_FINDINGS


def test_script_parts_read_the_outbound_opening_and_label_answers() -> None:
    script = CallScript(
        opening_line="Thanks for calling Ravi Dental.",
        outbound_opening_line="Hi, this is Ravi Dental with a festive offer for you.",
        faqs=[FaqEntry(question="Any discounts?", answer="We give a 5% discount to seniors.")],
    )
    parts = script_parts(script, outbound=True)
    assert parts[0].where == "Opening line for calls it places"
    report = lint(parts)
    assert report.verdict == "promotional"
    assert {f.where for f in report.findings if f.severity == "strong"} == {
        "Opening line for calls it places"
    }
    assert any(f.severity == "soft" and f.where.startswith("Answer to") for f in report.findings)


def test_a_raw_script_is_read_whole() -> None:
    script = CallScript(raw_override="You call to remind patients. Mention our mega sale.")
    assert lint(script_parts(script)).verdict == "promotional"


@pytest.mark.parametrize(
    ("classification", "source", "purpose"),
    [
        ("service", "existing_customer", "service_own_customer"),
        ("service", "inbound_enquiry", "relationship_enquiry"),
        ("service", "web_form_optin", "relationship_enquiry"),
        ("service", "offline_form_optin", "relationship_enquiry"),
        ("service", "purchased_list", "unclear"),
        ("service", None, "unclear"),
        ("promotional", "existing_customer", "promotional"),
        ("transactional", "existing_customer", "unclear"),
    ],
)
def test_campaign_purpose_follows_the_choices_the_client_made(
    classification: str, source: str | None, purpose: str
) -> None:
    assert campaign_purpose(classification, source).purpose == purpose


def test_lead_source_purpose_follows_the_declared_basis() -> None:
    assert lead_source_purpose("application").window == "3 months from their application"
    assert lead_source_purpose("inquiry").window == "7 days from their enquiry"
