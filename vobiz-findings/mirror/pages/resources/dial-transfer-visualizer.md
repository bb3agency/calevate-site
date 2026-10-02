> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Dial XML Transfer Visualizer

> Step through a Vobiz call transfer: a caller reaches your AI agent, Dial rings a human on standby, and the human accepts or rejects. Every webhook body and every piece of XML, in order.

export const DV_A = "6f1d4a92-3b77-4d0e-9f2a-1c8b5e7d0431";
export const DV_B = "c0a58e17-9d24-4f6b-8a13-72e5b4c9d806";
export const DV_CALLER = "+14155550111";
export const DV_DID = "+14155550100";
export const DV_HUMAN = "+14155559911";
export const DV_HOST = "your-server.example";

export const DV_STREAM_XML = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Record fileFormat="mp3" recordSession="true"
          callbackUrl="https://your-server.example/record-ready"
          callbackMethod="POST" redirect="false" playBeep="false"/>
  <Stream bidirectional="true" keepCallAlive="true"
          contentType="audio/x-l16;rate=8000">
    wss://your-server.example/agent-stream
  </Stream>
</Response>`;

export const DV_DIAL_XML = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="+14155550100"
        timeout="30"
        timeLimit="1800"
        dialMusic="https://your-server.example/prompt/hold"
        callbackUrl="https://your-server.example/dial-events"
        callbackMethod="POST"
        action="https://your-server.example/dial-result"
        method="POST">
    <Number>+14155559911</Number>
  </Dial>
</Response>`;

export const DV_HOLD_XML = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Speak>Please hold while I connect you to a colleague.</Speak>
  <Wait length="1"/>
</Response>`;

export const DV_RESUME_XML = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Stream bidirectional="true" keepCallAlive="true"
          contentType="audio/x-l16;rate=8000">
    wss://your-server.example/agent-stream?resume=true
  </Stream>
</Response>`;

export const DV_WRAP_XML = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Speak>Thanks for calling. Goodbye.</Speak>
  <Hangup/>
</Response>`;

export const DV_NO_XML = "HTTP 204 · no XML expected.\n\nRealtime Dial callbacks only notify you. They cannot steer the call - only the action URL can.";

export const DV_PHASES = {
  incoming: {
    tag: "Inbound call",
    tone: "",
    title: "A caller reaches your Vobiz number",
    desc: "Vobiz answers nothing on its own. It requests the answer URL of the application attached to your number and waits for XML. Nothing is connected yet.",
    nodes: {
      caller: "calling",
      app: "idle",
      human: "standby"
    },
    lines: {
      ca: "ring",
      sa: "off",
      sh: "standby"
    },
    dir: "in",
    label: "answer webhook",
    route: "POST /answer",
    payload: {
      Event: "StartApp",
      CallUUID: "6f1d4a92-3b77-4d0e-9f2a-1c8b5e7d0431",
      From: "+14155550111",
      To: "+14155550100",
      Direction: "inbound",
      CallStatus: "ringing",
      ParentAuthID: "MA_EXAMPLE00001"
    },
    outLabel: "the XML you return",
    outKind: "xml",
    out: DV_STREAM_XML,
    next: "Open the AI stream"
  },
  ai: {
    tag: "AI on the line",
    tone: "",
    title: "Your AI agent is talking to the caller",
    desc: "Stream opened a bidirectional WebSocket. Caller audio arrives as media frames, your agent replies with playAudio, and recordSession captures the whole session. A human waits on standby.",
    nodes: {
      caller: "talk",
      app: "live",
      human: "standby"
    },
    lines: {
      ca: "voice",
      sa: "stream",
      sh: "standby"
    },
    dir: "in",
    label: "media frame",
    route: "WSS /agent-stream",
    payload: {
      event: "media",
      streamId: "6f1d4a92-3b77-4d0e-9f2a-1c8b5e7d0431",
      media: {
        track: "inbound",
        chunk: 274,
        payload: "<base64 L16 8k>"
      }
    },
    outLabel: "what your agent sends back",
    outKind: "json",
    out: {
      event: "playAudio",
      media: {
        contentType: "audio/x-l16",
        sampleRate: 8000,
        payload: "<base64 speech>"
      }
    },
    next: "Caller asks for a human"
  },
  handoff: {
    tag: "Handoff",
    tone: "",
    title: "Your app hands the A leg to Dial XML",
    desc: "The caller wants a person. Your app transfers the A leg to a URL that returns Dial XML. That interrupts Stream immediately - the AI WebSocket closes - and Vobiz starts executing the new document.",
    nodes: {
      caller: "hold",
      app: "gone",
      human: "standby"
    },
    lines: {
      ca: "hold",
      sa: "dropped",
      sh: "standby"
    },
    dir: "out",
    label: "transfer request",
    route: "POST /Call/6f1d4a92…/",
    payload: {
      legs: "aleg",
      aleg_url: "https://your-server.example/handoff-xml",
      aleg_method: "POST"
    },
    outLabel: "the XML aleg_url returns",
    outKind: "xml",
    out: DV_DIAL_XML,
    next: "Ring the human"
  },
  ring: {
    tag: "Ringing",
    tone: "",
    title: "Vobiz rings the human on standby",
    desc: "Dial creates a second call - the B leg - from your callerId to the human. The caller hears the dialMusic prompt while it rings, and the ring window is capped by timeout=30. The human can accept or reject.",
    nodes: {
      caller: "hold",
      app: "gone",
      human: "ring"
    },
    lines: {
      ca: "hold",
      sa: "dropped",
      sh: "ring"
    },
    choice: true,
    dir: "in",
    label: "dialMusic fetch",
    route: "POST /prompt/hold",
    payload: {
      Event: "DialRemoteSounds",
      CallUUID: "6f1d4a92-3b77-4d0e-9f2a-1c8b5e7d0431",
      From: "+14155550111",
      To: "+14155550100",
      CallStatus: "in-progress"
    },
    outLabel: "your hold XML",
    outKind: "xml",
    out: DV_HOLD_XML,
    next: ""
  },
  answer: {
    tag: "Answered",
    tone: "ok",
    title: "The human picks up",
    desc: "DialAnswer fires the moment the handset is answered - before audio is bridged. The B leg now has its own UUID, and DialBLegFrom is the callerId the human actually saw.",
    nodes: {
      caller: "hold",
      app: "gone",
      human: "answered"
    },
    lines: {
      ca: "hold",
      sa: "dropped",
      sh: "ring"
    },
    dir: "in",
    label: "callbackUrl",
    route: "POST /dial-events",
    payload: {
      Event: "DialAnswer",
      DialAction: "answer",
      DialBLegStatus: "answer",
      DialALegUUID: "6f1d4a92-3b77-4d0e-9f2a-1c8b5e7d0431",
      DialBLegUUID: "c0a58e17-9d24-4f6b-8a13-72e5b4c9d806",
      DialBLegFrom: "+14155550100",
      DialBLegTo: "+14155559911",
      DialBLegPosition: "1"
    },
    outLabel: "your response",
    outKind: "text",
    out: DV_NO_XML,
    next: "Bridge the legs"
  },
  bridge: {
    tag: "Bridged",
    tone: "ok",
    title: "Vobiz bridges the caller to the human",
    desc: "DialConnected means audio flows both ways between the two legs. The timeLimit clock starts here - the seconds spent ringing never counted against it. The AI is gone; the session recording keeps running.",
    nodes: {
      caller: "talk",
      app: "gone",
      human: "talk"
    },
    lines: {
      ca: "voice",
      sa: "dropped",
      sh: "bridged"
    },
    dir: "in",
    label: "callbackUrl",
    route: "POST /dial-events",
    payload: {
      Event: "DialConnected",
      DialAction: "connected",
      DialBLegStatus: "connected",
      DialALegUUID: "6f1d4a92-3b77-4d0e-9f2a-1c8b5e7d0431",
      DialBLegUUID: "c0a58e17-9d24-4f6b-8a13-72e5b4c9d806",
      DialBLegTo: "+14155559911",
      DialBLegPosition: "1"
    },
    outLabel: "your response",
    outKind: "text",
    out: DV_NO_XML,
    next: "Human hangs up"
  },
  wrap: {
    tag: "Dial complete",
    tone: "ok",
    title: "The human hangs up and Dial reports the result",
    desc: "DialHangup carries the only B-leg durations you will get: 11 seconds bridged, billed at the destination's 60-second minimum. Then the action URL fires once with the final DialStatus, and the XML you return owns the rest of the call.",
    nodes: {
      caller: "hold",
      app: "gone",
      human: "gone"
    },
    lines: {
      ca: "hold",
      sa: "dropped",
      sh: "end"
    },
    dir: "in",
    label: "callbackUrl, then action",
    route: "POST /dial-events → /dial-result",
    payload: {
      "1_callbackUrl": {
        Event: "DialHangup",
        DialAction: "hangup",
        DialBLegStatus: "hangup",
        DialBLegDuration: "11",
        DialBLegBillDuration: "60",
        DialBLegHangupCause: "NORMAL_CLEARING",
        DialBLegHangupCauseCode: "4000",
        DialBLegHangupCauseName: "Normal Hangup",
        DialBLegHangupSource: "Callee",
        DialBLegUUID: "c0a58e17-9d24-4f6b-8a13-72e5b4c9d806"
      },
      "2_action": {
        Event: "Redirect",
        DialStatus: "completed",
        DialRingStatus: "true",
        DialHangupCause: "NORMAL_CLEARING",
        DialALegUUID: "6f1d4a92-3b77-4d0e-9f2a-1c8b5e7d0431",
        DialBLegUUID: "c0a58e17-9d24-4f6b-8a13-72e5b4c9d806"
      }
    },
    outLabel: "the XML action returns",
    outKind: "xml",
    out: DV_WRAP_XML,
    next: "End the call"
  },
  reject: {
    tag: "Rejected",
    tone: "bad",
    title: "The human rejects the call",
    desc: "They decline, or the line is engaged. The B leg never bridges, so DialBLegDuration is 0 and nothing is billed for it. Any sipHeaders you set on Dial come back on this webhook with the X-VH- prefix.",
    nodes: {
      caller: "hold",
      app: "gone",
      human: "reject"
    },
    lines: {
      ca: "hold",
      sa: "dropped",
      sh: "fail"
    },
    dir: "in",
    label: "callbackUrl",
    route: "POST /dial-events",
    payload: {
      Event: "DialHangup",
      DialAction: "hangup",
      DialBLegStatus: "hangup",
      DialBLegDuration: "0",
      DialBLegBillDuration: "0",
      DialBLegHangupCause: "USER_BUSY",
      DialBLegHangupCauseCode: "3010",
      DialBLegHangupCauseName: "Busy Line",
      DialBLegHangupSource: "Vobiz",
      DialBLegUUID: "c0a58e17-9d24-4f6b-8a13-72e5b4c9d806",
      AnswerTime: "",
      "X-VH-Reason": "handoff"
    },
    outLabel: "your response",
    outKind: "text",
    out: DV_NO_XML,
    next: "Hand control back"
  },
  resume: {
    tag: "AI resumes",
    tone: "",
    title: "The action URL hands the call back to your AI",
    desc: "DialStatus is busy and DialBLegUUID is empty - the giveaway that nothing was ever bridged, even though the realtime DialHangup did carry a B-leg UUID. Returning a fresh Stream re-opens the WebSocket so your agent picks the conversation back up.",
    nodes: {
      caller: "talk",
      app: "live",
      human: "standby"
    },
    lines: {
      ca: "voice",
      sa: "stream",
      sh: "standby"
    },
    dir: "in",
    label: "action",
    route: "POST /dial-result",
    payload: {
      Event: "DialAction",
      DialStatus: "busy",
      DialRingStatus: "true",
      DialHangupCause: "USER_BUSY",
      DialALegUUID: "6f1d4a92-3b77-4d0e-9f2a-1c8b5e7d0431",
      DialBLegUUID: ""
    },
    outLabel: "the XML action returns",
    outKind: "xml",
    out: DV_RESUME_XML,
    next: "End the call"
  },
  end: {
    tag: "Call ended",
    tone: "",
    title: "The call ends and the ledger webhooks land",
    desc: "The A-leg hangup webhook covers the whole session - greeting, AI conversation, ring time and bridge - so its Duration of 26 seconds is always longer than DialBLegDuration. The recording callback follows once the file is downloadable.",
    nodes: {
      caller: "end",
      app: "end",
      human: "end"
    },
    lines: {
      ca: "end",
      sa: "end",
      sh: "end"
    },
    dir: "in",
    label: "hangup_url, then Record callbackUrl",
    route: "POST /hangup → /record-ready",
    payload: {
      "1_hangup": {
        Event: "Hangup",
        CallUUID: "6f1d4a92-3b77-4d0e-9f2a-1c8b5e7d0431",
        CallStatus: "completed",
        Duration: "26",
        BillDuration: "60",
        HangupCause: "NORMAL_CLEARING",
        HangupCauseCode: "4000",
        HangupSource: "Answer XML"
      },
      "2_record": {
        Event: "RecordStop",
        RecordUrl: "https://media.vobiz.ai/v1/Account/MA_EXAMPLE00001/Recording/9a0e0208.mp3",
        RecordingID: "9a0e0208-71bd-4c35-8e42-6db07f1a5c93",
        RecordingDuration: "24"
      }
    },
    outLabel: "your response",
    outKind: "text",
    out: "HTTP 204 · the call is over.\n\nThe hangup webhook is the authoritative end-of-call signal, whoever ended the call.",
    next: ""
  }
};

export const DV_SEQ = {
  base: ["incoming", "ai", "handoff", "ring"],
  accept: ["answer", "bridge", "wrap", "end"],
  reject: ["reject", "resume", "end"]
};

export const DV_STATES = {
  calling: "calling in",
  live: "ai streaming",
  talk: "on call",
  hold: "on hold",
  ring: "ringing",
  answered: "answered",
  reject: "rejected",
  standby: "on standby",
  gone: "disconnected",
  end: "ended",
  idle: "idle"
};

export const DvJson = ({value}) => <pre><code>{JSON.stringify(value, null, 2).split("\n").map((line, i) => {
  const m = line.match(/^(\s*)"([^"]+)":\s?(.*)$/);
  if (!m) return <div key={i}>{line}</div>;
  const isNum = (/^-?\d+(\.\d+)?,?$/).test(m[3]);
  return <div key={i}>
        {m[1]}<span className="dv-k">"{m[2]}"</span>:{m[3] ? " " : ""}
        <span className={isNum ? "dv-nm" : "dv-v"}>{m[3]}</span>
      </div>;
})}</code></pre>;

export const DvXml = ({text}) => <pre><code>{text.split("\n").map((line, i) => {
  if (line.trim().startsWith("<?xml")) return <div key={i} className="dv-decl">{line}</div>;
  const parts = line.split(/([\w:.-]+="[^"]*"|<\/?[A-Za-z][\w:.-]*|\/>|>)/g).filter(p => p !== "" && p !== undefined);
  return <div key={i}>{parts.map((p, j) => {
    if ((/^[\w:.-]+="/).test(p)) {
      const eq = p.indexOf("=");
      return <span key={j}><span className="dv-attr">{p.slice(0, eq)}</span>=<span className="dv-val">{p.slice(eq + 1)}</span></span>;
    }
    if ((/^<\/?[A-Za-z]/).test(p) || p === ">" || p === "/>") return <span key={j} className="dv-tag">{p}</span>;
    return <span key={j} className="dv-plain">{p}</span>;
  })}</div>;
})}</code></pre>;

export const DvNode = ({cls, role, face, num, state}) => <div className={"dv-node " + cls}>
    <div className="dv-mod" data-eq={["live", "talk", "ring", "hold"].includes(state) ? state : "off"}>
      <div className="dv-role"><span className={"dv-led on-" + state} />{role}</div>
      <div className={"dv-avatar is-" + state}>{face}</div>
      <div className="dv-num">{num}</div>
      <div className="dv-eq"><i /><i /><i /><i /><i /></div>
      <div className={"dv-st on-" + state}>{DV_STATES[state]}</div>
    </div>
  </div>;

export const DvCable = ({id, d, state}) => <g className={"dv-cg is-" + state}>
    <path className="dv-glow" d={d} />
    <path className="dv-cable" d={d} />
    <circle className="dv-pulse" style={{
  offsetPath: `path('${d}')`
}} />
  </g>;

export const DialVisualizer = () => {
  const [branch, setBranch] = React.useState(null);
  const [step, setStep] = React.useState(0);
  const [playing, setPlaying] = React.useState(false);
  const seq = branch ? DV_SEQ.base.concat(DV_SEQ[branch]) : DV_SEQ.base;
  const idx = Math.min(step, seq.length - 1);
  const ph = DV_PHASES[seq[idx]];
  const atChoice = Boolean(ph.choice) && branch === null;
  const atEnd = idx === seq.length - 1 && !atChoice;
  const pad = n => String(n).padStart(2, "0");
  React.useEffect(() => {
    if (!playing) return undefined;
    if (atChoice || atEnd) {
      setPlaying(false);
      return undefined;
    }
    const t = window.setTimeout(() => setStep(s => s + 1), 2400);
    return () => window.clearTimeout(t);
  }, [playing, idx, atChoice, atEnd]);
  const reset = () => {
    setPlaying(false);
    setBranch(null);
    setStep(0);
  };
  const fork = which => {
    if (atChoice) {
      setBranch(which);
      setStep(idx + 1);
    }
  };
  React.useEffect(() => {
    const onKey = e => {
      if (e.key === " " || e.key === "ArrowRight") {
        if (!atChoice && !atEnd) {
          e.preventDefault();
          setPlaying(false);
          setStep(s => s + 1);
        }
      } else if (e.key === "ArrowLeft") {
        setPlaying(false);
        setStep(s => Math.max(0, s - 1));
      } else if (e.key === "1") fork("accept"); else if (e.key === "2") fork("reject"); else if (e.key === "0") reset();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  const CA = "M180,165 C300,190 372,190 470,165";
  const SA = "M530,165 C650,136 720,110 828,94";
  const SH = "M530,165 C650,194 720,222 828,240";
  return <div className="dial-visualizer not-prose">
      <main className="dv-shell">
      <div className="dv-intro">
        <p className="dv-eyebrow">Interactive transfer sequence</p>
        <h1>Hand a live call from your AI agent to a human.</h1>
        <p className="dv-lede">
          A transfer is never one call. <code>Dial</code> creates a second call and bridges it to the caller
          already on the line, so the two legs are timed, billed and reported separately. Step through the
          handoff below - the panel on the right is the webhook Vobiz sends you, and under it is the XML you
          send back.
        </p>
      </div>

      <div className="dv-board">
        <div className="dv-scenewrap"><div className="dv-scene">
          <div className="dv-radar"><span /><span /><span /></div>
          <svg className="dv-cables" viewBox="0 0 1000 330" preserveAspectRatio="none">
            <DvCable d={CA} state={ph.lines.ca} />
            <DvCable d={SA} state={ph.lines.sa} />
            <DvCable d={SH} state={ph.lines.sh} />
          </svg>
          <DvNode cls="is-caller" role="Caller · A leg" face="🧑" num={DV_CALLER} state={ph.nodes.caller} />
          <div className="dv-node is-switch">
            <div className="dv-mod">
              <div className="dv-role">the switch</div>
              <div className="dv-avatar">V</div>
              <div className="dv-num">{DV_DID}</div>
              <div className={"dv-st on-" + (seq[idx] === "end" ? "idle" : "talk")}>
                {seq[idx] === "end" ? "idle" : "switching"}
              </div>
            </div>
          </div>
          <DvNode cls="is-app" role="Your app · AI agent" face="🤖" num="media stream" state={ph.nodes.app} />
          <DvNode cls="is-human" role="Human agent · B leg" face="🧑‍💼" num={DV_HUMAN} state={ph.nodes.human} />
        </div></div>

        <div className="dv-rail">
          <span>step <b>{pad(idx + 1)}</b></span>
          <span className="dv-count">{idx + 1} / {seq.length}</span>
          <span className="dv-track"><i style={{
    width: idx / (seq.length - 1) * 100 + "%"
  }} /></span>
        </div>

        <div className="dv-deck">
          <div className="dv-pane">
            <div className={"dv-stepcard" + (ph.tone === "ok" ? " is-ok" : ph.tone === "bad" ? " is-bad" : "")}>
              <div className="dv-cap"><span className="dv-n">{pad(idx + 1)}</span>{ph.tag}</div>
              <h3>{ph.title}</h3>
              <p>{ph.desc}</p>
            </div>

            {atChoice ? <div className="dv-choice">
                <button type="button" className="dv-accept" onClick={() => fork("accept")}>✓ Human accepts</button>
                <button type="button" className="dv-reject" onClick={() => fork("reject")}>✕ Human rejects</button>
              </div> : <button type="button" className="dv-cta" disabled={atEnd} onClick={() => {
    setPlaying(false);
    setStep(s => s + 1);
  }}>
                <span>{atEnd ? "Call complete" : ph.next || "Next"}</span>
                <span aria-hidden="true">→</span>
              </button>}

            <div className="dv-util">
              <button type="button" onClick={() => {
    if (atEnd) reset();
    setPlaying(!playing);
  }}>
                {playing ? "❙❙ Pause" : "▶ Auto-play"}
              </button>
              <button type="button" onClick={() => {
    setPlaying(false);
    setStep(s => Math.max(0, s - 1));
  }}>← Back</button>
              <button type="button" onClick={reset}>↻ Restart</button>
            </div>
            <div className="dv-hint">keys · <b>space</b> next · <b>1 / 2</b> accept or reject · <b>0</b> restart</div>

            <div className="dv-logtitle">Sequence</div>
            <div className="dv-log">
              {seq.slice(0, idx + 1).map((id, i) => {
    const p = DV_PHASES[id];
    const col = p.tone === "ok" ? "var(--dv-mint)" : p.tone === "bad" ? "var(--dv-rose)" : "var(--dv-sig)";
    return <div key={id} className={"dv-row" + (i === idx ? " is-cur" : "")}>
                    <span className="dv-i">{pad(i + 1)}</span>
                    <span>{p.title}</span>
                    <span className="dv-dot" style={{
      background: col
    }} />
                  </div>;
  }).reverse()}
            </div>
          </div>

          <div className="dv-pane">
            <div className="dv-term">
              <div className="dv-head">
                <span className="dv-dir">{ph.dir === "in" ? "Vobiz → your server" : "your server → Vobiz"}</span>
                <span>· {ph.label}</span>
                <span className="dv-path">{ph.route}</span>
              </div>
              <DvJson value={ph.payload} />
            </div>

            <div className="dv-term">
              <div className="dv-head"><span>{ph.outLabel}</span></div>
              {ph.outKind === "xml" ? <DvXml text={ph.out} /> : ph.outKind === "json" ? <DvJson value={ph.out} /> : <pre><code className="dv-plain">{ph.out}</code></pre>}
            </div>

            <div className="dv-note">
              <b>Field names and values come from live Vobiz test calls.</b> Numbers, UUIDs and hostnames are
              documentation placeholders, and each payload is trimmed to the fields that matter - real bodies also
              carry STIR, billing, rate and timestamp fields.
            </div>
          </div>
        </div>
      </div>

      <div className="dv-footer-link">
        <a href="/docs/xml/dial">Read the Dial reference <span aria-hidden="true">→</span></a>
        <a href="/docs/call/transfer-call">Transfer a call API <span aria-hidden="true">→</span></a>
        <a href="/docs/concepts/hangup-causes">Hangup causes <span aria-hidden="true">→</span></a>
      </div>
      </main>
    </div>;
};

<DialVisualizer />


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.