> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Blog

> Guides, deep-dives, and product updates from the Vobiz team - voice AI engineering, telephony best practices, and platform announcements.

## Latest posts

export const POSTS = [{
  href: "/blogs/what-is-voice-transcription-asr",
  header: "What Is Voice Transcription (ASR)?",
  title: "What is Voice Transcription (ASR)? How Telephony Affects Accuracy",
  category: "Transcription",
  date: "July 3, 2026",
  read: 18,
  gradient: "linear-gradient(to bottom right, #14b8a6, #0891b2, #1d4ed8)",
  excerpt: `How ASR works, streaming vs batch, Word Error Rate, and why telephony audio (bandwidth, codecs, packet loss) decides accuracy before the model runs.`
}, {
  href: "/blogs/what-is-caller-id-cnam",
  header: "Caller ID & CNAM",
  title: "What is Caller ID and CNAM? How Caller Name Display Works",
  category: "Phone Numbers",
  date: "July 1, 2026",
  read: 13,
  gradient: "linear-gradient(to bottom right, #f43f5e, #db2777, #a21caf)",
  excerpt: `The CNAM dip against LIDB, the 15-character limit, STIR/SHAKEN, branded calling, and why caller display decides answer rates.`
}, {
  href: "/blogs/what-is-call-routing",
  header: "What Is Call Routing?",
  title: "What is Call Routing? Types, How It Works & Examples",
  category: "Voice API",
  date: "June 29, 2026",
  read: 12,
  gradient: "linear-gradient(to bottom right, #6366f1, #2563eb, #0e7490)",
  excerpt: `How the routing engine and ACD decide where calls go, 11 routing types (round-robin, skills-based, LCR), and dynamic routing via API.`
}, {
  href: "/blogs/what-is-webrtc",
  header: "What Is WebRTC?",
  title: "What is WebRTC? How It Works, APIs, Codecs & Voice AI",
  category: "WebRTC",
  date: "June 26, 2026",
  read: 13,
  gradient: "linear-gradient(to bottom right, #8b5cf6, #9333ea, #a21caf)",
  excerpt: `The full handshake (getUserMedia, SDP, ICE/STUN/TURN, SRTP), the core APIs, codecs, WebRTC vs SIP, and why voice AI still needs a PSTN bridge.`
}, {
  href: "/blogs/what-is-answering-machine-detection",
  header: "What Is AMD?",
  title: "What is Answering Machine Detection (AMD)? How It Works",
  category: "Outbound",
  date: "June 25, 2026",
  read: 16,
  gradient: "linear-gradient(to bottom right, #f59e0b, #ea580c, #be123c)",
  excerpt: `How AMD tells a human from voicemail, sync vs async detection, the accuracy-vs-latency trade-off, and gating the stream for voice AI.`
}, {
  href: "/blogs/what-is-multi-level-ivr",
  header: "What Is a Multi-Level IVR?",
  title: "What is a Multi-Level IVR? Nested Menus, Routing & How to Build One",
  category: "IVR",
  date: "June 24, 2026",
  read: 13,
  gradient: "linear-gradient(to bottom right, #d946ef, #7c3aed, #4338ca)",
  excerpt: `How nested IVR menus work (DTMF + speech), menu-tree design and depth limits, and a real VobizXML build that callers don't abandon.`
}, {
  href: "/blogs/what-is-e164-phone-number-formatting",
  header: "What Is E.164 Formatting?",
  title: "What is E.164 Phone Number Formatting? The Complete Guide",
  category: "Phone Numbers",
  date: "June 22, 2026",
  read: 13,
  gradient: "linear-gradient(to bottom right, #0ea5e9, #2563eb, #4338ca)",
  excerpt: `+country code, up to 15 digits, no leading zeros, how E.164 works, examples by country, and how to validate it with libphonenumber.`
}, {
  href: "/blogs/toll-free-vs-local-vs-mobile-numbers",
  header: "Toll-Free vs Local vs Mobile",
  title: "Toll-Free vs Local vs Mobile Numbers: The 2026 Guide",
  category: "Phone Numbers",
  date: "June 19, 2026",
  read: 13,
  gradient: "linear-gradient(to bottom right, #10b981, #0d9488, #0e7490)",
  excerpt: `US prefixes, area codes, A2P/10DLC, SMS deliverability, cost, caller perception, and when to use each number type.`
}, {
  href: "/blogs/what-is-a-virtual-phone-number",
  header: "What Is a Virtual Phone Number?",
  title: "What Is a Virtual Phone Number? How It Works, Types & Uses",
  category: "Phone Numbers",
  date: "June 17, 2026",
  read: 14,
  gradient: "linear-gradient(to bottom right, #06b6d4, #2563eb, #4338ca)",
  excerpt: `A real number with no SIM or copper line, how cloud routing works, the types, virtual vs DID vs landline, and the voice-AI angle.`
}, {
  href: "/blogs/what-is-a-call-leg",
  header: "What Is a Call Leg?",
  title: "What Is a Call Leg? A-Leg vs B-Leg in Programmable Voice",
  category: "Telecom Basics",
  date: "June 16, 2026",
  read: 8,
  gradient: "linear-gradient(to bottom right, #0891b2, #0284c7, #1d4ed8)",
  excerpt: `What a call leg is, the difference between A-leg and B-leg, how calls get bridged, and why legs matter for transfers, billing, and recording.`
}, {
  href: "/blogs/automated-calling-answering-machine-detection",
  header: "Automated Calling & AMD",
  title: "Scaling Outbound: Mastering Automated Calling & Answering Machine Detection in 2026",
  category: "Outbound",
  date: "June 16, 2026",
  read: 15,
  gradient: "linear-gradient(to bottom right, #4f46e5, #2563eb, #0369a1)",
  excerpt: `Dialer pacing, CPS vs concurrency, how AMD works, and gating the media stream for voice AI.`
}, {
  href: "/blogs/context-aware-call-transfers",
  header: "Context-Aware Call Transfers",
  title: "Mastering Call Transfers in 2026: The Switch to Context-Aware Programmable Voice",
  category: "Programmable Voice",
  date: "June 16, 2026",
  read: 14,
  gradient: "linear-gradient(to bottom right, #9333ea, #7c3aed, #4338ca)",
  excerpt: `Blind vs warm vs supervised, the SIP REFER/Replaces/UUI protocol layer, per-leg transfer, and AI-to-human handoff with context.`
}, {
  href: "/blogs/call-recording-apis-compliant-pipelines",
  header: "Call Recording APIs",
  title: "Building Compliant Pipelines: The State of Call Recording APIs in 2026",
  category: "Compliance",
  date: "June 16, 2026",
  read: 14,
  gradient: "linear-gradient(to bottom right, #059669, #0d9488, #0e7490)",
  excerpt: `Dual vs mono channels, transcription pipelines, encryption & retention, and consent/PCI/GDPR-compliant recording design.`
}, {
  href: "/blogs/intelligent-call-escalations",
  header: "Intelligent Call Escalations",
  title: "Designing Intelligent Call Escalations: Going Beyond Blind Transfers in 2026",
  category: "Contact Center",
  date: "June 16, 2026",
  read: 15,
  gradient: "linear-gradient(to bottom right, #e11d48, #dc2626, #c2410c)",
  excerpt: `Escalation triggers, skills-based routing, AI-to-human handoff with context, and conference-based monitor/whisper/barge.`
}, {
  href: "/blogs/what-is-a-did-number",
  header: "What Is a DID Number?",
  title: "What is a DID Number? Direct Inward Dialing Explained",
  category: "Phone Numbers",
  date: "June 15, 2026",
  read: 14,
  gradient: "linear-gradient(to bottom right, #3b82f6, #4f46e5, #6d28d9)",
  excerpt: `How direct inward dialing routes a call to a specific endpoint, DID types, number porting, and DID vs virtual numbers.`
}, {
  href: "/blogs/what-is-number-masking",
  header: "What is Number Masking?",
  title: "What is Number Masking? How Two-Way Call Masking Works",
  category: "Privacy",
  date: "June 12, 2026",
  read: 14,
  img: "/images/blog/what-is-number-masking.png",
  excerpt: `How one-way and two-way call masking work, why two-way needs two numbers, a full call flow, use cases, and how to build it.`
}, {
  href: "/blogs/what-is-voip",
  header: "What is VoIP?",
  title: "What is VoIP?",
  category: "VoIP",
  date: "June 10, 2026",
  read: 11,
  img: "/images/blog/what-is-voip.png",
  excerpt: `How VoIP works (codecs, SIP, RTP), the types of VoIP, equipment, bandwidth, call quality, costs, and setup.`
}, {
  href: "/blogs/what-is-sip",
  header: "What is SIP?",
  title: "What is SIP (Session Initiation Protocol)?",
  category: "SIP",
  date: "June 10, 2026",
  read: 11,
  img: "/images/blog/what-is-sip.png",
  excerpt: `What SIP is, how it works (methods, message flow, registration), components, trunking channels, and security.`
}, {
  href: "/blogs/sip-vs-voip",
  header: "SIP vs VoIP",
  title: "SIP vs VoIP: What's the Difference?",
  category: "SIP",
  date: "June 10, 2026",
  read: 10,
  img: "/images/blog/sip-vs-voip.png",
  excerpt: `VoIP is the category, SIP is the protocol. The differences, SIP vs VoIP phones, hosted vs self-managed, and which to choose.`
}, {
  href: "/blogs/what-is-an-ivr",
  header: "What is an IVR?",
  title: "What is an IVR (Interactive Voice Response)?",
  category: "IVR",
  date: "June 10, 2026",
  read: 10,
  img: "/images/blog/what-is-an-ivr.png",
  excerpt: `How IVR works (DTMF, speech, conversational AI), the three levels, use cases, benefits, and how to build one.`
}, {
  href: "/blogs/what-is-sip-trunking",
  header: "What is SIP Trunking?",
  title: "What is SIP Trunking?",
  category: "SIP",
  date: "June 10, 2026",
  read: 9,
  img: "/images/blog/what-is-sip-trunking.png",
  excerpt: `What SIP trunking is, how it works (signaling vs media), how it replaces PRI, and how to choose a provider.`
}, {
  href: "/blogs/call-center-optimization-with-ai",
  header: "Call Center Optimization with AI",
  title: "Call Center Optimization with AI: The Complete Guide",
  category: "Contact Center",
  date: "June 9, 2026",
  read: 10,
  img: "/images/blog/call-center-optimization-with-ai.png",
  excerpt: `Strategies, metrics, and the AI building blocks, IVR, AI voice agents, OTP verification, plus how the telephony underneath works.`
}, {
  href: "/blogs/what-is-a-voice-api",
  header: "What is a Voice API?",
  title: "What is a Voice API?",
  category: "Voice API",
  date: "June 9, 2026",
  read: 8,
  img: "/images/blog/what-is-a-voice-api.png",
  excerpt: `What a voice API is, how it streamlines business communication, and Vobiz's flat ₹0.65/min INR pricing.`
}, {
  href: "/blogs/what-is-a-landline-number",
  header: "What is a Landline Number?",
  title: "What is a Landline Number?",
  category: "Phone Numbers",
  date: "June 9, 2026",
  read: 6,
  img: "/images/blog/what-is-a-landline-number.png",
  excerpt: `Understand what a landline number is, its role, types, and benefits, and how modern VoIP alternatives compare.`
}];

export const PAGE_SIZE = 9;

export const BlogIndex = () => {
  const [page, setPage] = useState(1);
  const totalPages = Math.ceil(POSTS.length / PAGE_SIZE);
  const current = Math.min(page, totalPages);
  const start = (current - 1) * PAGE_SIZE;
  const visible = POSTS.slice(start, start + PAGE_SIZE);
  const go = n => setPage(Math.min(totalPages, Math.max(1, n)));
  const btn = "px-3 py-1.5 rounded-lg border border-gray-200 dark:border-zinc-800 text-gray-600 dark:text-gray-300 hover:border-primary/40 disabled:opacity-40 disabled:cursor-not-allowed transition";
  return <div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 not-prose my-6">
        {visible.map(p => <a key={p.href} href={p.href} className="group block rounded-2xl border border-gray-200 dark:border-zinc-800 overflow-hidden bg-white dark:bg-zinc-900 hover:shadow-md hover:border-primary/40 transition no-underline">
            {p.gradient ? <div className="relative h-40 p-4 flex flex-col justify-between" style={{
    backgroundImage: p.gradient
  }}>
                <span className="text-sm font-bold tracking-tight" style={{
    color: "rgba(255,255,255,0.9)"
  }}>Vobiz</span>
                <span className="text-lg font-semibold leading-snug" style={{
    color: "#ffffff"
  }}>{p.header}</span>
              </div> : <img src={p.img} alt={p.header} className="h-40 w-full object-cover" />}
            <div className="p-5">
              <span className="inline-block text-xs font-medium px-2.5 py-1 rounded-full bg-gray-100 dark:bg-zinc-800 text-gray-600 dark:text-gray-300 mb-3">{p.category}</span>
              <div className="text-base font-semibold text-gray-900 dark:text-gray-100 leading-snug">{p.title}</div>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-2 leading-snug">{p.excerpt}</p>
              <div className="text-xs text-gray-400 dark:text-gray-500 mt-4">{p.date} · {p.read} min read</div>
            </div>
          </a>)}
      </div>

      {totalPages > 1 && <div className="flex items-center justify-center gap-2 mt-10 not-prose text-sm font-medium">
          <button onClick={() => go(current - 1)} disabled={current === 1} className={btn}>← Prev</button>
          {Array.from({
    length: totalPages
  }, (_, i) => i + 1).map(n => <button key={n} onClick={() => go(n)} className={n === current ? "h-9 w-9 rounded-lg border border-primary bg-primary text-white transition" : "h-9 w-9 rounded-lg border border-gray-200 dark:border-zinc-800 text-gray-600 dark:text-gray-300 hover:border-primary/40 transition"}>
              {n}
            </button>)}
          <button onClick={() => go(current + 1)} disabled={current === totalPages} className={btn}>Next →</button>
        </div>}
    </div>;
};

<BlogIndex />


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.