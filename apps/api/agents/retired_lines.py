"""The spoken lines the trade plans used to teach every business, kept only to find them (D-962).

Until 2 Nov 2026 each trade's step plan (`agents/trade_playbooks`) carried one example line per
step in Telugu, Hindi and English, and a ready-made script stored them on the agent's steps as
"it sounds like". The same words then reached every business of a type, and one of them made a
claim no call's data backed: a Rytu Khata agent told a farmer "you enquired with us earlier, do
you still want it?" (founder, 2 Nov 2026). The plans now keep only the structure of a call, and
every line a caller hears is written for the business.

This frozen set is what is left of those lines, for two readers and nothing else:

* the script writer's lint refuses a drafted line identical to one of them
  (`retired_line_problem`), so a model that saw them before cannot hand them back;
* the job that takes them off live agents (`apps/workers/retired_line_strip.py`) clears a step
  still holding one word for word; a line anybody edited is never touched.

It is never shown to a model and never offered as an example. It includes the lines earlier
corrections replaced (D-888's bedrooms and weekend lines, D-894's Telugu "సరే అండి," opener), so
an agent made before those corrections is found too.
"""

from __future__ import annotations

from typing import Final

RETIRED_LINES: Final[frozenset[str]] = frozenset(
    {
        # Telugu
        "అడ్వైజర్ తో మాట్లాడటానికి ఈ రోజు కుదురుతుందా, రేపు కుదురుతుందా అండి?",
        "అడ్వైజర్ తో మాట్లాడటానికి ఏ రోజు కుదురుతుంది అండి, ఈ రోజా రేపా?",
        "ఆ డీటెయిల్ నా దగ్గర లేదు అండి, టీమ్ కన్ఫర్మ్ చేస్తారు.",
        "ఇప్పుడు ఏ కంపెనీ పాలసీ ఉంది అండి?",
        "ఈ వారం ఏ రోజు స్లాట్ కావాలి అండి?",
        "ఈ వారంలో మార్నింగ్ కుదురుతుందా, ఈవెనింగ్ కుదురుతుందా అండి?",
        "ఎన్ని బీహెచ్కే కావాలి అండి?",
        "ఏ ఏరియా లో చూస్తున్నారు?",
        "ఏ ఐటమ్ కావాలి అండి?",
        "ఏ ఐటమ్ కావాలి?",
        "ఏ కోర్స్ గురించి అడుగుతున్నారు?",
        "ఏ కోర్స్ చూస్తున్నారు అండి?",
        "ఏ డాక్టర్ ని చూపించుకోవాలి అనుకుంటున్నారు అండి?",
        "ఏ ప్రాబ్లం కోసం చూపించుకోవాలి అండి?",
        "ఏ రోజు కుదురుతుంది అండి, ఈ రోజా రేపా?",
        "ఏ రోజు కుదురుతుంది అండి, మార్నింగ్ కావాలా ఈవెనింగ్ కావాలా?",
        "ఏ సర్వీస్ కావాలి అండి?",
        "ఏ సర్వీస్ కావాలి?",
        "ఏం కావాలో కొంచెం చెప్తారా అండి?",
        "ఒకసారి సైట్ విజిట్ కి రండి అండి, ఈ వీకెండ్ కుదురుతుందా?",
        "ఒకసారి సైట్ విజిట్ కి రండి అండి, రేపు కుదురుతుందా, ఎల్లుండి కుదురుతుందా?",
        "కౌన్సెలింగ్ సెషన్ కి ఈ వారం ఏ రోజు కుదురుతుంది అండి?",
        "టూ బీహెచ్కే కావాలా, త్రీ బీహెచ్కే కావాలా అండి?",
        "డాక్టర్ ని ఎప్పుడు చూపించుకోవాలి, ఈ రోజా రేపా?",
        "డెమో క్లాస్ కి వీక్ డే కుదురుతుందా, వీకెండ్ కుదురుతుందా అండి?",
        "డెలివరీ ఏ ఏరియా కి చేయాలి అండి?",
        "డెలివరీ కావాలా, మీరే వచ్చి తీసుకుంటారా అండి?",
        "పర్లేదు అండి, మీకు ఎప్పుడు కుదురుతుంది, సాయంత్రమా రేపా?",
        "బడ్జెట్ ఎంత వరకు అనుకుంటున్నారు అండి?",
        "మార్నింగ్ కుదురుతుందా, ఈవెనింగ్ కుదురుతుందా అండి?",
        "మార్నింగ్ స్లాట్ కావాలా, ఈవెనింగ్ స్లాట్ కావాలా అండి?",
        "మీ రెన్యూవల్ ఎప్పుడు ఉంది అండి?",
        "మీ వెహికల్ ఏ మోడల్ అండి?",
        "మీ వెహికల్ ఏ మోడల్?",
        "మీకు ఏ రోజు కుదురుతుంది అండి?",
        "మీకు ఏం కావాలో చెప్తారా?",
        "మీరు ఇంతకు ముందు అడ్మిషన్ గురించి ఎంక్వైరీ చేశారు కదా, ఇంకా ఆలోచిస్తున్నారా అండి?",
        "మీరు ఇంతకు ముందు అపాయింట్మెంట్ గురించి అడిగారు కదా, ఇంకా కావాలా అండి?",
        "మీరు ఇంతకు ముందు పాలసీ గురించి అడిగారు కదా, ఇంకా చూస్తున్నారా అండి?",
        "మీరు ఇంతకు ముందు ప్రాపర్టీ గురించి ఎంక్వైరీ చేశారు కదా, ఇంకా చూస్తున్నారా అండి?",
        "మీరు ఇంతకు ముందు మా దగ్గర ఎంక్వైరీ చేశారు కదా, ఇంకా కావాలా అండి?",
        "మీరు ఇంతకు ముందు మా ప్రొడక్ట్స్ గురించి అడిగారు కదా, ఇంకా కావాలా అండి?",
        "మీరు ఇంతకు ముందు మా సర్వీస్ గురించి అడిగారు కదా, ఇంకా కావాలా అండి?",
        "మీరు ఇంతకు ముందు సర్వీస్ గురించి అడిగారు కదా, ఇంకా చేయించాలా అండి?",
        "మీరు చెప్పింది టీమ్ కి చెప్తాను, వాళ్ళు కన్ఫర్మ్ చేస్తారు. ఇంకేమైనా కావాలా?",
        "మీరే వస్తారా, మేము ఇంటికి రావాలా అండి?",
        "వన్ కేజీ కావాలా, హాఫ్ కేజీ కావాలా అండి?",
        "వెహికల్ పికప్ కావాలా, మీరే తీసుకొస్తారా అండి?",
        "సరే అండి, ఏ ఏరియా లో చూస్తున్నారు?",
        "సరే అండి, ఏ ఐటమ్ కావాలి?",
        "సరే అండి, ఏ కోర్స్ గురించి అడుగుతున్నారు?",
        "సరే అండి, ఏ సర్వీస్ కావాలి?",
        "సరే అండి, డాక్టర్ ని ఎప్పుడు చూపించుకోవాలి, ఈ రోజా రేపా?",
        "సరే అండి, మీ వెహికల్ ఏ మోడల్?",
        "సరే అండి, మీకు ఏం కావాలో చెప్తారా?",
        "సరే అండి, మీరు చెప్పింది టీమ్ కి చెప్తాను, వాళ్ళు కన్ఫర్మ్ చేస్తారు. ఇంకేమైనా కావాలా?",
        "సరే అండి, హెల్త్ పాలసీ కావాలా, లైఫ్ పాలసీ కావాలా?",
        "సర్వీస్ కావాలా, రిపేర్ కావాలా అండి?",
        "సర్వీస్ కి ఏ రోజు కుదురుతుంది అండి, ఈ రోజా రేపా?",
        "సైట్ విజిట్ కి రేపు కుదురుతుందా, ఎల్లుండి కుదురుతుందా అండి?",
        "సైట్ విజిట్ కి సాటర్డే కుదురుతుందా, సండే కుదురుతుందా అండి?",
        "స్టూడెంట్ ఏ క్లాస్ చదువుతున్నారు అండి?",
        "హెల్త్ పాలసీ కావాలా, లైఫ్ పాలసీ కావాలా?",
        # Hindi
        "अभी किस कंपनी की पॉलिसी है जी?",
        "आप आएँगे या हम घर पर आएँ?",
        "आपका रिन्यूअल कब है जी?",
        "आपकी गाड़ी कौन से मॉडल की है जी?",
        "आपको कौन सा दिन ठीक रहेगा जी?",
        "आपने पहले अपॉइंटमेंट के बारे में पूछा था, अभी भी चाहिए?",
        "आपने पहले एडमिशन के बारे में इन्क्वायरी की थी, अभी भी सोच रहे हैं?",
        "आपने पहले पॉलिसी के बारे में पूछा था, अभी भी देख रहे हैं?",
        "आपने पहले प्रॉपर्टी के बारे में इन्क्वायरी की थी, अभी भी देख रहे हैं?",
        "आपने पहले सर्विस के बारे में पूछा था, अभी भी करानी है?",
        "आपने पहले हमसे इन्क्वायरी की थी, अभी भी चाहिए?",
        "आपने पहले हमारी सर्विस के बारे में पूछा था, अभी भी चाहिए?",
        "आपने पहले हमारे प्रोडक्ट्स के बारे में पूछा था, अभी भी चाहिए?",
        "इस हफ़्ते किस दिन का स्लॉट चाहिए जी?",
        "इस हफ़्ते मॉर्निंग ठीक रहेगा या ईवनिंग?",
        "एक बार साइट विज़िट कर लीजिए जी, इस वीकेंड ठीक रहेगा?",
        "एक बार साइट विज़िट कर लीजिए जी, कल ठीक रहेगा या परसों?",
        "एडवाइज़र से बात करने के लिए, आज ठीक रहेगा या कल?",
        "एडवाइज़र से बात करने के लिए, कौन सा दिन ठीक रहेगा, आज या कल?",
        "काउंसलिंग सेशन के लिए, इस हफ़्ते कौन सा दिन ठीक रहेगा?",
        "कितने बीएचके चाहिए जी?",
        "किस डॉक्टर को दिखाना चाहते हैं जी?",
        "किस प्रॉब्लम के लिए दिखाना है जी?",
        "कोई बात नहीं जी, कब ठीक रहेगा, शाम को या कल?",
        "कौन सा आइटम चाहिए जी?",
        "कौन सा कोर्स देख रहे हैं जी?",
        "कौन सा दिन ठीक रहेगा जी, मॉर्निंग या ईवनिंग?",
        "कौन सा दिन ठीक रहेगा, आज या कल?",
        "कौन सी सर्विस चाहिए जी?",
        "क्या चाहिए, थोड़ा बताएँगे जी?",
        "गाड़ी पिकअप करवानी है या आप खुद लाएँगे?",
        "टू बीएचके चाहिए या थ्री बीएचके?",
        "ठीक है जी, आपकी गाड़ी कौन से मॉडल की है?",
        "ठीक है जी, आपकी बात टीम तक पहुँचा देते हैं, वो कन्फर्म करेंगे। और कुछ चाहिए?",
        "ठीक है जी, किस एरिया में देख रहे हैं?",
        "ठीक है जी, किस कोर्स के बारे में पूछ रहे हैं?",
        "ठीक है जी, कौन सा आइटम चाहिए?",
        "ठीक है जी, कौन सी सर्विस चाहिए?",
        "ठीक है जी, डॉक्टर को कब दिखाना है, आज या कल?",
        "ठीक है जी, बताइए क्या चाहिए?",
        "ठीक है जी, हेल्थ पॉलिसी चाहिए या लाइफ पॉलिसी?",
        "डिलीवरी किस एरिया में करनी है जी?",
        "डिलीवरी चाहिए या आप खुद आकर ले लेंगे?",
        "डेमो क्लास के लिए वीकडे ठीक रहेगा या वीकेंड?",
        "बजट कितने तक सोच रहे हैं जी?",
        "मॉर्निंग का स्लॉट चाहिए या ईवनिंग का?",
        "मॉर्निंग ठीक रहेगा या ईवनिंग?",
        "वन केजी चाहिए या हाफ केजी?",
        "वो डिटेल अभी मेरे पास नहीं है जी, टीम कन्फर्म करेगी।",
        "सर्विस करानी है या रिपेयर?",
        "सर्विस के लिए कौन सा दिन ठीक रहेगा, आज या कल?",
        "साइट विज़िट के लिए कल ठीक रहेगा या परसों?",
        "साइट विज़िट के लिए सैटरडे ठीक रहेगा या संडे?",
        "स्टूडेंट किस क्लास में है जी?",
        # English
        "Alright, I'll pass this to the team and they'll confirm it. Anything else?",
        "Are you looking at a two or a three BHK?",
        "For a demo class, would a weekday or a weekend suit you?",
        "For a site visit, would Saturday or Sunday suit you?",
        "For a site visit, would tomorrow or the day after suit you?",
        "For a talk with an advisor, would today or tomorrow suit you?",
        "How many bedrooms are you looking for?",
        "How much would you like, one kg or half a kg?",
        "I don't have that detail with me, the team will confirm it.",
        "Is it a regular service or a repair?",
        "Is there a doctor you would like to see?",
        "No problem, when would suit you better, this evening or tomorrow?",
        "Roughly what budget do you have in mind?",
        "Shall we deliver it, or would you pick it up?",
        "Shall we pick the vehicle up, or will you bring it in?",
        "Sure, is this about a health policy or a life policy?",
        "Sure, what can I help you with?",
        "Sure, when would you like to see the doctor, today or tomorrow?",
        "Sure, which area are you looking in?",
        "Sure, which course are you asking about?",
        "Sure, which item would you like?",
        "Sure, which service do you need?",
        "Sure, which vehicle and model is it?",
        "This week, would a morning or an evening work for you?",
        "What are you looking for?",
        "What is the visit for?",
        "When is your renewal due?",
        "Which area should it be delivered to?",
        "Which class or year is the student in?",
        "Which course are you looking at?",
        "Which day suits you for the service, today or tomorrow?",
        "Which day suits you to talk to an advisor, today or tomorrow?",
        "Which day suits you, morning or evening?",
        "Which day suits you, today or tomorrow?",
        "Which day suits you?",
        "Which day this week suits you for a counselling session?",
        "Which day this week would you like a slot?",
        "Which item would you like?",
        "Which model is your vehicle?",
        "Which service would you like?",
        "Who are you insured with at the moment?",
        "Will you come in, or should someone come to you?",
        "Would a morning or an evening slot suit you?",
        "Would a morning or an evening suit you?",
        "Would you like to see the site, maybe this weekend?",
        "Would you like to see the site, tomorrow or the day after?",
        "You asked about an appointment earlier, would you still like one?",
        "You had asked about a policy earlier, are you still looking?",
        "You had asked about a service earlier, does the vehicle still need one?",
        "You had asked about our products earlier, are you still interested?",
        "You had asked about our service earlier, do you still need it?",
        "You had enquired about a property earlier, are you still looking?",
        "You had enquired about admission earlier, are you still considering it?",
        "You had enquired with us earlier, are you still interested?",
    }
)


def is_retired_line(text: str) -> bool:
    """Is `text`, trimmed, one of the lines the plans used to teach every business?"""
    return text.strip() in RETIRED_LINES


def retired_line_problem(path: str, text: str) -> str | None:
    """The script writer's problem for a drafted line identical to a retired one."""
    if not is_retired_line(text):
        return None
    return (
        f"{path}: is a ready-made line written for every business; write this business's own "
        "line from the owner's words, or leave it empty"
    )


__all__ = ["RETIRED_LINES", "is_retired_line", "retired_line_problem"]
