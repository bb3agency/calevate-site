"""The SHORT caller notice, in English, Telugu and Hindi (D-943).

`caller_notice.py` drafts the full notice a client's counsel works from. This is the short
one a business can actually put in front of a caller: on its website, in a WhatsApp
message, read out at the counter. DPDP §5(3) lets a person read a notice in English or
any Eighth Schedule language; Telugu and Hindi are the two this client base speaks.

SAME FACTS, FEWER WORDS. Everything here is derived from the same draft
(`build_caller_notice`): the items collected, the retention periods, the switches. It
says nothing the long notice does not, and its rights paragraph matches `/legal/privacy`
and the DPA: access, correction, erasure, nomination, a grievance, the Data Protection
Board, and an answer within 90 days (DPDP Rules 2025, official per the PIB backgrounder of
17 Nov 2025, `docs/research/research_notes/Calevate market and technology edge/
india_regulation.md` §3). Its blanks are the long notice's blanks, spelled the same, so a
value the client fills once fills both.

THE TELUGU AND HINDI ARE MACHINE-DRAFTED and say so in their own disclaimer: a native
speaker and the client's advocate read them before they reach a caller. A client's own
field labels are quoted as the client wrote them, never translated by us.
"""

from __future__ import annotations

from typing import Final, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.caller_notice import (
    BUSINESS_CONTACT,
    BUSINESS_NAME,
    STANDARD_ITEMS,
    build_caller_notice,
    retention_category,
)
from apps.api.compliance.models import RIGHTS_RESPONSE_DAYS

NoticeLanguage = Literal["en", "te", "hi"]
NOTICE_LANGUAGES: Final[tuple[NoticeLanguage, ...]] = ("en", "te", "hi")

DISCLAIMER: Final[dict[NoticeLanguage, str]] = {
    "en": (
        "DRAFT — not legal advice. Generated from your own settings. Have your advocate check "
        "it before you use it. Anything in double braces is a blank only you can fill."
    ),
    "te": (
        "DRAFT — not legal advice. This Telugu wording was machine-drafted: have a native "
        "speaker and your advocate check it before you use it. Anything in double braces is "
        "a blank only you can fill."
    ),
    "hi": (
        "DRAFT — not legal advice. This Hindi wording was machine-drafted: have a native "
        "speaker and your advocate check it before you use it. Anything in double braces is "
        "a blank only you can fill."
    ),
}

#: The standard collected items, per language. A client's own fields are quoted as written.
_ITEMS: Final[dict[NoticeLanguage, tuple[str, ...]]] = {
    "en": (
        "your phone number",
        "a recording, a transcript and a short summary of the call",
        "your name, what you asked for and what was agreed",
        "when the call happened and how long it lasted",
    ),
    "te": (
        "మీ ఫోన్ నంబర్",
        "కాల్ రికార్డింగ్, మాట్లాడినదాని లిఖిత ప్రతి, కాల్ యొక్క చిన్న సారాంశం",
        "మీ పేరు, మీరు అడిగినది, ఏమి అంగీకరించామో",
        "కాల్ ఎప్పుడు జరిగింది, ఎంతసేపు జరిగింది",
    ),
    "hi": (
        "आपका फ़ोन नंबर",
        "कॉल की रिकॉर्डिंग, बातचीत का लिखित रूप और कॉल का छोटा सारांश",
        "आपका नाम, आपने क्या माँगा और क्या तय हुआ",
        "कॉल कब हुई और कितनी देर चली",
    ),
}

_MEMORY_LINE: Final[dict[NoticeLanguage, str]] = {
    "en": "a short note of what you asked about, kept so we know it if you call again",
    "te": "మీరు మళ్ళీ కాల్ చేసినప్పుడు తెలియడానికి, మీరు అడిగినదాని చిన్న నోట్",
    "hi": "आपने जो पूछा उसका छोटा नोट, ताकि आप दोबारा कॉल करें तो हमें पता रहे",
}

#: Retention categories (`caller_notice._CATEGORY_LABELS` keys), per language.
_RETENTION: Final[dict[NoticeLanguage, dict[str, str]]] = {
    "en": {
        "recording": "The recording of your call",
        "transcript": "The transcript",
        "lead": "The details noted from your call",
        "caller_memory": "The short note of what you asked about",
        "engine_payload": "The technical record of the call",
        "kb": "Older versions of the business's own information",
    },
    "te": {
        "recording": "మీ కాల్ రికార్డింగ్",
        "transcript": "మాట్లాడినదాని లిఖిత ప్రతి",
        "lead": "మీ కాల్ నుండి నమోదు చేసిన వివరాలు",
        "caller_memory": "మీరు అడిగినదాని చిన్న నోట్",
        "engine_payload": "కాల్ యొక్క సాంకేతిక రికార్డు",
        "kb": "వ్యాపారం సమాచారం యొక్క పాత ప్రతులు",
    },
    "hi": {
        "recording": "आपकी कॉल की रिकॉर्डिंग",
        "transcript": "बातचीत का लिखित रूप",
        "lead": "आपकी कॉल से नोट किया गया विवरण",
        "caller_memory": "आपने जो पूछा उसका छोटा नोट",
        "engine_payload": "कॉल का तकनीकी रिकॉर्ड",
        "kb": "व्यवसाय की अपनी जानकारी के पुराने रूप",
    },
}

_DAYS: Final[dict[NoticeLanguage, str]] = {"en": "{n} days", "te": "{n} రోజులు", "hi": "{n} दिन"}

_TEMPLATE: Final[dict[NoticeLanguage, str]] = {
    "en": """# {business}: your information when you call us

{business} is responsible for the information collected on our calls. Our calling and AI
assistant are run for us by Calevate, which uses this information only on our instructions.

Calls to and from us may be handled by an AI voice assistant, and every call is recorded.
If you ask, the assistant always tells you that it is an AI and that the call is recorded.

## What we collect

{items}

## Why

To answer your enquiry, to do what you ask us to on the call, and to keep a record of what
was agreed.

## How long we keep it

{retention}

## Your rights

You can ask for a copy of what we hold about you, ask us to correct or erase it, name
someone to act for you, or make a complaint. We answer within {days} days. To stop our calls,
you can also tell the assistant on the call.

To ask: {contact}

If you are not satisfied with our answer, you can complain to the Data Protection Board of
India.
""",
    "te": """# {business}: మీరు మాకు కాల్ చేసినప్పుడు మీ సమాచారం

మా కాల్స్‌లో సేకరించే సమాచారానికి {business} బాధ్యత వహిస్తుంది. మా కాలింగ్ మరియు AI
సహాయకుడిని మా తరఫున Calevate నడుపుతుంది; అది ఈ సమాచారాన్ని మా సూచనల మేరకు మాత్రమే
ఉపయోగిస్తుంది.

మా కాల్స్‌ను AI వాయిస్ సహాయకుడు చేయవచ్చు లేదా స్వీకరించవచ్చు, మరియు ప్రతి కాల్ రికార్డ్
అవుతుంది. మీరు అడిగితే, తాను AI అని, కాల్ రికార్డ్ అవుతోందని సహాయకుడు ఎప్పుడూ చెబుతుంది.

## మేము సేకరించేవి

{items}

## ఎందుకు

మీ ప్రశ్నకు జవాబు ఇవ్వడానికి, కాల్‌లో మీరు అడిగినది చేయడానికి, ఏమి అంగీకరించామో దాని
రికార్డు ఉంచడానికి.

## ఎంత కాలం ఉంచుతాము

{retention}

## మీ హక్కులు

మా దగ్గర ఉన్న మీ సమాచారం యొక్క ప్రతిని అడగవచ్చు, దాన్ని సరిచేయమని లేదా తొలగించమని
అడగవచ్చు, మీ తరఫున వ్యవహరించడానికి మరొకరిని నియమించవచ్చు, లేదా ఫిర్యాదు చేయవచ్చు. మేము
{days} రోజుల్లోపు జవాబు ఇస్తాము. మా కాల్స్ ఆపమని కాల్‌లోనే సహాయకుడికి కూడా చెప్పవచ్చు.

అడగడానికి: {contact}

మా జవాబుతో మీకు సంతృప్తి లేకపోతే, డేటా ప్రొటెక్షన్ బోర్డ్ ఆఫ్ ఇండియా (Data Protection
Board of India) కు ఫిర్యాదు చేయవచ్చు.
""",
    "hi": """# {business}: जब आप हमें कॉल करते हैं, तब आपकी जानकारी

हमारी कॉल पर इकट्ठा की गई जानकारी के लिए {business} ज़िम्मेदार है। हमारी कॉलिंग और AI सहायक
हमारी ओर से Calevate चलाता है, जो यह जानकारी केवल हमारे निर्देशों पर इस्तेमाल करता है।

हमारी कॉल AI वॉइस सहायक कर सकता है या उठा सकता है, और हर कॉल रिकॉर्ड होती है। आप पूछें तो
सहायक हमेशा बताएगा कि वह AI है और कॉल रिकॉर्ड हो रही है।

## हम क्या इकट्ठा करते हैं

{items}

## क्यों

आपके सवाल का जवाब देने, कॉल पर आपने जो माँगा वह करने, और जो तय हुआ उसका रिकॉर्ड रखने के लिए।

## कितने समय तक रखते हैं

{retention}

## आपके अधिकार

आप हमारे पास रखी अपनी जानकारी की कॉपी माँग सकते हैं, उसे सुधारने या मिटाने के लिए कह सकते
हैं, अपनी ओर से किसी और को नामित कर सकते हैं, या शिकायत कर सकते हैं। हम {days} दिनों के भीतर
जवाब देंगे। हमारी कॉल बंद करवाने के लिए आप कॉल पर ही सहायक से भी कह सकते हैं।

पूछने के लिए: {contact}

अगर आप हमारे जवाब से संतुष्ट नहीं हैं, तो आप भारत के डेटा संरक्षण बोर्ड (Data Protection
Board of India) में शिकायत कर सकते हैं।
""",
}


async def build_short_notice(
    session: AsyncSession, *, tenant_id: UUID, language: NoticeLanguage
) -> str:
    """The short notice, in `language`, from this account's own settings."""
    draft = await build_caller_notice(session, tenant_id=tenant_id)
    items = list(_ITEMS[language])
    if draft.caller_memory_on:
        items.append(_MEMORY_LINE[language])
    # The client's own field labels, quoted as written: a label is the client's word for
    # what they ask, and a translation of it would be ours.
    items.extend(item.what for item in draft.collected if item.what not in STANDARD_ITEMS)
    labels = _RETENTION[language]
    retention = [
        f"- {labels.get(retention_category(line.what), line.what)}: "
        + _DAYS[language].format(n=line.days)
        for line in draft.retention
    ]
    return _TEMPLATE[language].format(
        business=BUSINESS_NAME,
        contact=BUSINESS_CONTACT,
        days=RIGHTS_RESPONSE_DAYS,
        items="\n".join(f"- {item}" for item in items),
        retention="\n".join(retention) or "- {{HOW LONG YOU KEEP CALL RECORDS}}",
    )


__all__ = ["DISCLAIMER", "NOTICE_LANGUAGES", "NoticeLanguage", "build_short_notice"]
