> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# SIP Trunk vs WebSocket Visualizer

> Step through both Vobiz connectivity paths side by side - a SIP trunk authenticated by IP ACL or SIP credentials, and a WebSocket app driven by your Answer URL. Outbound and inbound, with the media leg drawn on every step.

export const SwFlows = () => {
  const [st, setSt] = React.useState({
    sip: {
      dir: "outbound",
      i: 0
    },
    ws: {
      dir: "outbound",
      i: 0
    }
  });
  const [playing, setPlaying] = React.useState({
    sip: false,
    ws: false
  });
  const flowOf = p => SW_FLOWS[p][st[p].dir];
  const lastOf = p => SW_FLOWS[p][st[p].dir].steps.length - 1;
  const setDir = (p, dir) => {
    setPlaying(v => ({
      ...v,
      [p]: false
    }));
    setSt(v => ({
      ...v,
      [p]: {
        dir,
        i: 0
      }
    }));
  };
  const move = (p, d) => {
    setPlaying(v => ({
      ...v,
      [p]: false
    }));
    setSt(v => {
      const max = SW_FLOWS[p][v[p].dir].steps.length - 1;
      return {
        ...v,
        [p]: {
          ...v[p],
          i: Math.max(0, Math.min(max, v[p].i + d))
        }
      };
    });
  };
  const reset = p => {
    setPlaying(v => ({
      ...v,
      [p]: false
    }));
    setSt(v => ({
      ...v,
      [p]: {
        ...v[p],
        i: 0
      }
    }));
  };
  const togglePlay = p => {
    setPlaying(v => {
      const on = !v[p];
      if (on && st[p].i >= lastOf(p)) setSt(s => ({
        ...s,
        [p]: {
          ...s[p],
          i: 0
        }
      }));
      return {
        ...v,
        [p]: on
      };
    });
  };
  const anyPlaying = playing.sip || playing.ws;
  const toggleBoth = () => {
    if (anyPlaying) {
      setPlaying({
        sip: false,
        ws: false
      });
      return;
    }
    setSt(s => {
      const n = {
        ...s
      };
      ["sip", "ws"].forEach(k => {
        if (s[k].i >= SW_FLOWS[k][s[k].dir].steps.length - 1) n[k] = {
          ...s[k],
          i: 0
        };
      });
      return n;
    });
    setPlaying({
      sip: true,
      ws: true
    });
  };
  React.useEffect(() => {
    const live = ["sip", "ws"].filter(k => playing[k]);
    if (!live.length) return undefined;
    const id = window.setInterval(() => {
      setSt(prev => {
        const next = {
          ...prev
        };
        live.forEach(k => {
          const max = SW_FLOWS[k][prev[k].dir].steps.length - 1;
          if (prev[k].i < max) next[k] = {
            ...prev[k],
            i: prev[k].i + 1
          };
        });
        return next;
      });
    }, 2200);
    return () => window.clearInterval(id);
  }, [playing]);
  React.useEffect(() => {
    setPlaying(prev => {
      let changed = false;
      const next = {
        ...prev
      };
      ["sip", "ws"].forEach(k => {
        if (prev[k] && st[k].i >= SW_FLOWS[k][st[k].dir].steps.length - 1) {
          next[k] = false;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [st]);
  const column = p => {
    const F = SW_FLOWS[p];
    const f = flowOf(p);
    const steps = f.steps;
    const i = Math.min(st[p].i, steps.length - 1);
    const cur = steps[i];
    const lit = new Set([0]);
    const doneSegs = new Set();
    let hot = -1, hotUp = false, now = 0;
    for (let k = 0; k <= i; k++) {
      const s = steps[k];
      if (s.seg !== undefined) {
        if (k === i) {
          hot = s.seg;
          hotUp = Boolean(s.up);
          now = s.up ? s.seg : s.seg + 1;
        } else doneSegs.add(s.seg);
        lit.add(s.seg);
        lit.add(s.seg + 1);
      }
      if (s.node !== undefined) {
        lit.add(s.node);
        if (k === i) now = s.node;
      }
      if (s.done && k === i) {
        f.nodes.forEach((_, x) => lit.add(x));
        now = -1;
      }
    }
    const speaker = cur.seg !== undefined ? cur.up ? cur.seg + 1 : cur.seg : cur.node;
    const live = steps.slice(0, i + 1).some(s => s.media);
    const custIdx = f.nodes.findIndex(id => id === "pbx" || id === "app");
    const vIdx = f.nodes.indexOf("vobiz");
    const rTop = Math.min(custIdx, vIdx), rBot = Math.max(custIdx, vIdx);
    const lastNode = f.nodes.length - 1;
    const stageKids = [];
    f.nodes.forEach((id, x) => {
      const n = SW_N[id];
      const isInt = f.internal === x;
      const lbl = hot === x && cur.lbl ? cur.lbl : isInt ? live ? "agent audio" : "internal" : "";
      stageKids.push(<div className="sw-cell" key={"cell-" + id} style={{
        gridRow: 2 * x + 1
      }}>
          <div className={"sw-node" + (x === now ? " is-now" : lit.has(x) ? " is-lit" : "")} data-k={n.k}>
            <div className="sw-icon" aria-hidden="true">{n.icon}</div>
            <div className="sw-nbody">
              <div className="sw-role">{n.role}</div>
              <div className="sw-name">{n.name}</div>
              <div className="sw-meta">{n.meta}</div>
            </div>
          </div>
          {cur.bubble && speaker === x ? <div className="sw-bubble">{String(cur.bubble).split(/\*\*(.+?)\*\*/g).map((part, bi) => bi % 2 ? <b key={bi}>{part}</b> : <span key={bi}>{part}</span>)}</div> : null}
        </div>);
      if (x === lastNode) return;
      stageKids.push(<div key={"conn-" + id} style={{
        gridRow: 2 * x + 2
      }} className={"sw-conn" + (hot === x ? " is-hot" : "") + (hot === x && hotUp ? " is-up" : "") + (doneSegs.has(x) ? " is-done" : "") + (isInt ? " is-int" : "") + (isInt && live ? " is-live" : "")}>
          <i /><span className="sw-dot" />{lbl ? <em>{lbl}</em> : null}
        </div>);
    });
    const tickOn = steps.map((ignored, k) => k <= i);
    return <section className="sw-col" data-p={p} key={p}>
        <div className="sw-head">
          <div className="sw-num" aria-hidden="true">{F.num}</div>
          <div className="sw-tag"><i />{F.tag}</div>
          <h3>{F.label}</h3>
          <p className="sw-sub">{F.sub}</p>
          <div className="sw-auth">
            {F.authPre} <b>{F.authA}</b> {F.authMid} <b>{F.authB}</b>
          </div>
          <div className="sw-hops"><i />{F.hops}</div>
          <div className="sw-ctrl"><i />{F.ctrl}</div>
        </div>

        <div className="sw-tabs">
          {SW_TABS.map(([d, n, t]) => <button type="button" key={d} className={"sw-tab" + (st[p].dir === d ? " is-on" : "")} onClick={() => setDir(p, d)}>{n}<b>{t}</b></button>)}
        </div>

        <div className="sw-stage">
          <div className={"sw-rail" + (live ? " is-on" : "")} style={{
      gridRow: 2 * rTop + 1 + " / " + (2 * rBot + 2)
    }}>
            <div className="sw-trk" />
            <span className="sw-cap is-t" /><span className="sw-cap is-b" />
            <span className="sw-pk is-d" /><span className="sw-pk is-d2" />
            <span className="sw-pk is-u" /><span className="sw-pk is-u2" />
            <div className="sw-rlbl">{live ? F.rail.name : F.rail.idle}</div>
          </div>

          {stageKids}
        </div>

        <div className="sw-step" aria-live="polite">
          <div className="sw-scap">
            <span className="sw-sidx">{String(i + 1).padStart(2, "0")}</span>
            <span className="sw-sof">/ {String(steps.length).padStart(2, "0")} · {st[p].dir}</span>
          </div>
          <h4>{cur.title}</h4>
          <p>{cur.desc}</p>
          {cur.chips ? <div className="sw-chips">{cur.chips.map(c => <span className="sw-chip" key={c.join("-")}>{c[0]}{c[1] ? <b>{c[1]}</b> : null}</span>)}</div> : null}
        </div>

        <div className="sw-ctrls">
          <button type="button" onClick={() => move(p, -1)} disabled={i === 0}>← Back</button>
          <button type="button" className="sw-go" onClick={() => move(p, 1)} disabled={i >= steps.length - 1}>
            {i >= steps.length - 1 ? "Flow complete" : "Next step"}
          </button>
          <button type="button" onClick={() => togglePlay(p)}>{playing[p] ? "❚❚ Pause" : "▶ Play"}</button>
          <button type="button" onClick={() => reset(p)} aria-label="Restart this flow">↻</button>
          <span className="sw-count">{String(i + 1).padStart(2, "0")} / {String(steps.length).padStart(2, "0")}</span>
        </div>

        <div className="sw-ticks" role="progressbar" aria-label="Flow progress" aria-valuemin="0" aria-valuemax={steps.length} aria-valuenow={i + 1}>
          {tickOn.map((on, k) => <i key={steps[k].title} className={on ? "is-on" : ""} />)}
        </div>
      </section>;
  };
  return <div className="sip-ws-visualizer not-prose">
      <main className="sw-shell">
        <div className="sw-masthead">
          <div>
            <p className="sw-eyebrow">Connectivity paths</p>
            <h1>Two ways to put a call on Vobiz.</h1>
            <p className="sw-lede">
              Same carrier network underneath, two different front doors. With a <b>SIP trunk</b> your PBX
              talks to Vobiz over SIP and authenticates with an IP allowlist or SIP credentials. With
              <b> WebSockets</b> your application talks to Vobiz over HTTPS and a <code>{"wss://"}</code> socket -
              no PBX in the middle. On the SIP side your endpoint terminates the call and <b>then</b> hands
              audio to the agent; on the socket side your server already <b>is</b> the agent. Step through
              outbound and inbound on each - the media leg runs down the left gutter.
            </p>
          </div>
          <div className="sw-tools">
            <button type="button" className={"sw-tool" + (anyPlaying ? " is-on" : "")} onClick={toggleBoth}>
              {anyPlaying ? "❚❚ Pause both" : "▶ Play both"}
            </button>
          </div>
        </div>

        <div className="sw-cols">{column("sip")}{column("ws")}</div>

        <div className="sw-compare">
          <div className="sw-cbox" data-p="sip">
            <h4>SIP Trunk</h4>
            <p className="sw-use">Use it when you already run telephony infrastructure, or your AI platform speaks SIP.</p>
            <ul>
              <li><b>You bring</b><span>A PBX, softswitch, or a SIP-native platform - LiveKit, VAPI, Retell, ElevenLabs.</span></li>
              <li><b>Auth</b><span>An IP Access Control List <em>or</em> a SIP username and password. Pick one; both are never required.</span></li>
              <li><b>Control</b><span>No XML and no Answer URL. Your SIP endpoint drives the call itself. Outbound goes to the SIP domain of the trunk; inbound is forwarded to your Primary URI.</span></li>
              <li><b>Agent</b><span>Sits <em>behind</em> the SIP endpoint. The endpoint terminates SIP and creates the room, then the agent joins - one extra hop that is yours to run.</span></li>
              <li><b>Media</b><span>RTP over UDP between Vobiz and your endpoint - no retransmission, so no jitter from recovery.</span></li>
            </ul>
          </div>
          <div className="sw-cbox" data-p="ws">
            <h4>WebSocket</h4>
            <p className="sw-use">Use it when your agent is code and you want Vobiz to talk to it directly.</p>
            <ul>
              <li><b>You bring</b><span>An HTTPS server that returns VobizXML, plus a <code>{"wss://"}</code> endpoint.</span></li>
              <li><b>Auth</b><span>Your API credentials on the REST call. No SIP registration, no PBX.</span></li>
              <li><b>Control</b><span>You drive the call with <em>VobizXML</em>. Both directions start the same way: Vobiz fetches your Answer URL, you return XML, and Vobiz runs it. A <code>{"<Stream>"}</code> element hands the audio to your socket.</span></li>
              <li><b>Agent</b><span><em>Is</em> the server Vobiz connects to. There is nothing to terminate and no room to join, so the handoff hop disappears.</span></li>
              <li><b>Media</b><span>Audio and events share one bidirectional socket, so barge-in is yours to control.</span></li>
            </ul>
          </div>
        </div>

        <p className="sw-note">
          <b>These are not mutually exclusive.</b> A SIP trunk can deliver a call into Vobiz, and that same
          call can then be piped to your WebSocket server with a <code>{"<Stream>"}</code> element. SIP
          handles the routing, the socket handles the audio.
        </p>

        <div className="sw-footer-link">
          <a href="/docs/concepts/sip-vs-websockets">Read the full comparison <span aria-hidden="true">→</span></a>
          <a href="/docs/platform/sip/outbound-trunks">Outbound trunks <span aria-hidden="true">→</span></a>
          <a href="/docs/platform/sip/inbound-trunks">Inbound trunks <span aria-hidden="true">→</span></a>
          <a href="/docs/resources/stream-events-visualizer">Stream events visualizer <span aria-hidden="true">→</span></a>
        </div>
      </main>
    </div>;
};

export const SW_TABS = [["outbound", "Flow 01", "Outbound — you call out"], ["inbound", "Flow 02", "Inbound — they call you"]];

export const SW_N = {
  pbx: {
    k: "cust",
    icon: "▤",
    role: "Your side",
    name: "SIP endpoint / PBX",
    meta: "LiveKit · VAPI · Retell · Asterisk"
  },
  agent: {
    k: "agent",
    icon: "✳",
    role: "Behind it",
    name: "AI agent",
    meta: "STT → LLM → TTS"
  },
  app: {
    k: "cust",
    icon: "⬢",
    role: "Your side",
    name: "Your app / AI agent",
    meta: "HTTPS server + wss:// endpoint"
  },
  vobiz: {
    k: "vobiz",
    icon: "V",
    role: "Vobiz",
    name: "Vobiz",
    meta: "trunk · routing · media"
  },
  carrier: {
    k: "carrier",
    icon: "◈",
    role: "Telecom",
    name: "Carrier",
    meta: "PSTN termination & origination"
  },
  human: {
    k: "human",
    icon: "☎",
    role: "Person",
    name: "Caller / callee",
    meta: "+91 98765 43210"
  }
};

export const SW_FLOWS = {
  sip: {
    label: "SIP Trunk",
    tag: "Trunk",
    num: "01",
    sub: "Your PBX sends calls to a Vobiz SIP domain and receives them on your Primary URI.",
    authPre: "Auth ·",
    authA: "IP ACL",
    authMid: "or",
    authB: "SIP user + password",
    hops: "5 steps · SIP terminates, then hands off to the agent",
    ctrl: "Instructions · none - your SIP endpoint drives the call itself",
    rail: {
      name: "RTP · audio",
      idle: "no media yet"
    },
    outbound: {
      nodes: ["agent", "pbx", "vobiz", "carrier", "human"],
      internal: 0,
      steps: [{
        seg: 0,
        lbl: "dial request",
        title: "Your AI agent asks its platform to dial out",
        desc: "The agent does not speak SIP itself. It asks the SIP endpoint sitting in front of it - a LiveKit or VAPI room, or your own PBX - to place the call on its behalf.",
        chips: [["agent → sip endpoint"], ["to", "+919876543210"]]
      }, {
        seg: 1,
        lbl: "SIP INVITE",
        title: "Your SIP endpoint knocks on the trunk",
        desc: "The endpoint points the call at the outbound trunk's own SIP domain. Vobiz checks the source against the trunk's IP Access Control List, or challenges for the SIP username and password on the attached credentials list.",
        chips: [["src IP", "203.0.113.10"], ["sip user", "acme_out"], ["from", "+912240000000"], ["to", "+919876543210"]],
        bubble: "Knock knock - I'm calling from **203.0.113.10**. Here are my **SIP credentials**. Please place a call from **+912240000000** to **+919876543210**."
      }, {
        node: 2,
        title: "Vobiz accepts and routes",
        desc: "The trunk is enabled and the caller passed auth, so Vobiz accepts the call, picks a route, and applies whatever the trunk has switched on - recording, AI transcription, PII redaction.",
        chips: [["trunk", "enabled"], ["domain", "39a32383.sip.vobiz.ai"], ["recording", "on"]]
      }, {
        seg: 2,
        lbl: "route out",
        title: "Vobiz hands the call to the carrier",
        desc: "Vobiz sends the call into the telecom network for termination to the destination number.",
        chips: [["termination"], ["₹0.45 / min"]]
      }, {
        seg: 3,
        lbl: "ring",
        title: "The carrier rings the callee",
        desc: "The destination handset rings on the PSTN or mobile network.",
        chips: [["pstn / mobile"]]
      }, {
        done: true,
        media: true,
        title: "Call connected",
        desc: "RTP now runs both ways between Vobiz and your SIP endpoint - the rail on the left. The endpoint then passes that audio inward to the agent over its own transport, which is the extra hop SIP carries and WebSocket does not.",
        chips: [["rtp", "bidirectional"], ["g.711 / g.722"], ["endpoint → agent", "internal"], ["trunk webhook", "POST"]]
      }]
    },
    inbound: {
      nodes: ["human", "carrier", "vobiz", "pbx", "agent"],
      internal: 3,
      steps: [{
        seg: 0,
        lbl: "dials",
        title: "Someone dials your Vobiz number",
        desc: "A caller dials one of the DIDs you bought from Vobiz.",
        chips: [["to", "+912240000000"]]
      }, {
        seg: 1,
        lbl: "inbound call",
        title: "The carrier delivers the call to Vobiz",
        desc: "The telecom network hands the inbound call over to Vobiz origination.",
        chips: [["origination"]]
      }, {
        node: 2,
        title: "Vobiz matches the number to an inbound trunk",
        desc: "Vobiz looks up which inbound trunk the dialled DID is linked to, and reads that trunk's Primary URI.",
        chips: [["did", "linked to trunk"], ["trunk", "enabled"], ["recording", "on"]]
      }, {
        seg: 2,
        lbl: "forward",
        title: "Vobiz forwards to your Primary URI",
        desc: "Vobiz sends the call on to the SIP destination configured on that trunk. If the trunk is disabled, Vobiz returns a SIP error to the carrier instead.",
        chips: [["primary uri", "sip:pbx.acme.com"]]
      }, {
        seg: 3,
        lbl: "terminate SIP",
        title: "Your endpoint terminates SIP and wakes the agent",
        desc: "LiveKit, VAPI, Retell or your own PBX answers the INVITE and creates the room or session the AI agent joins. Vobiz's job stops at the endpoint - this last handoff is yours.",
        chips: [["sip", "terminated"], ["room / session created"], ["agent joins"]]
      }, {
        done: true,
        media: true,
        title: "The agent is on the call",
        desc: "RTP runs between Vobiz and your endpoint, and the endpoint feeds that audio to the agent. The trunk webhook reports incoming.ringing, incoming.answered and incoming.ended as it goes.",
        chips: [["incoming.ringing"], ["incoming.answered"], ["incoming.ended"]]
      }]
    }
  },
  ws: {
    label: "WebSocket",
    tag: "Socket",
    num: "02",
    sub: "Vobiz never decides what a call should do. It fetches your Answer URL and executes the VobizXML you hand back - that XML is how you drive the call.",
    authPre: "Auth ·",
    authA: "API credentials",
    authMid: "+ your",
    authB: "Answer URL",
    hops: "4 steps · your server is the agent - no handoff",
    ctrl: "Instructions · Vobiz fetches your Answer URL and runs the VobizXML you return",
    rail: {
      name: "WSS · media + events",
      idle: "socket closed"
    },
    outbound: {
      nodes: ["app", "vobiz", "carrier", "human"],
      internal: -1,
      steps: [{
        seg: 0,
        lbl: "POST /Call",
        title: "Your app asks Vobiz to place the call",
        desc: "A single REST call. You give Vobiz the two numbers and the URL it should come back to once the callee picks up.",
        chips: [["from", "+912240000000"], ["to", "+919876543210"], ["answer_url", "/answer"], ["answer_method", "POST"]],
        bubble: "Knock knock - here is my **Answer URL**. Please place a call from **+912240000000** to **+919876543210** and come ask me what to do when they pick up."
      }, {
        node: 1,
        title: "Vobiz accepts and queues the call",
        desc: "You get a 200 with a call_uuid straight away. That means accepted and queued - not answered. The real state arrives on your callbacks.",
        chips: [["200", "accepted"], ["call_uuid returned"]]
      }, {
        seg: 1,
        lbl: "place call",
        title: "Vobiz places the call through the carrier",
        desc: "Vobiz sends the outbound call into the telecom network.",
        chips: [["termination"], ["₹0.65 / min"]]
      }, {
        seg: 2,
        lbl: "ring",
        title: "The carrier rings the callee",
        desc: "The destination handset rings. Nothing has been asked of your server yet.",
        chips: [["pstn / mobile"]]
      }, {
        seg: 0,
        up: true,
        lbl: "answer_url",
        title: "They pick up - Vobiz asks your Answer URL what to do",
        desc: "Vobiz has a live call and no instructions for it. It POSTs the call details to the answer_url you supplied and blocks, waiting for you to tell it what should happen next.",
        chips: [["POST", "/answer"], ["CallUUID"], ["from · to"], ["CallStatus", "in-progress"], ["awaiting", "VobizXML"]]
      }, {
        seg: 0,
        lbl: "VobizXML",
        title: "You reply with VobizXML - these are the instructions",
        desc: "The XML you return is the instruction set. A Stream element tells Vobiz to open a bidirectional socket to your endpoint; Speak, Play, Gather, Dial or Record would each steer the call somewhere else. Vobiz executes what it is given, in order.",
        chips: [["<Response>"], ["<Stream bidirectional=\"true\">"], ["wss://acme.com/agent"], ["</Response>"]]
      }, {
        media: true,
        done: true,
        title: "The socket opens - audio and events both ways",
        desc: "Vobiz streams caller audio to you as media frames; you stream your agent's speech back as playAudio. Barge-in, checkpoints and turn-taking are all yours to control.",
        chips: [["media frames", "in"], ["playAudio", "out"], ["clearAudio · checkpoint"]]
      }]
    },
    inbound: {
      nodes: ["human", "carrier", "vobiz", "app"],
      internal: -1,
      steps: [{
        seg: 0,
        lbl: "dials",
        title: "Someone dials your Vobiz number",
        desc: "A caller dials a DID that has a voice application attached to it.",
        chips: [["to", "+912240000000"]]
      }, {
        seg: 1,
        lbl: "inbound call",
        title: "The carrier delivers the call to Vobiz",
        desc: "The telecom network hands the inbound call to Vobiz.",
        chips: [["origination"]]
      }, {
        node: 2,
        title: "Vobiz finds the application on that number",
        desc: "Every number is attached to an application, and every application carries an answer_url. Vobiz answers nothing on its own - it goes and asks.",
        chips: [["app attached to did"], ["answer_url", "set"], ["fallback_answer_url"]]
      }, {
        seg: 2,
        lbl: "answer_url",
        title: "Vobiz asks your Answer URL what to do",
        desc: "Vobiz POSTs the call details to your server and waits. It will not answer, speak or stream anything until you tell it to. If your URL is unreachable or returns invalid XML, Vobiz tries the fallback - and drops the call if there is not one.",
        chips: [["POST", "/answer"], ["CallUUID"], ["from · to"], ["direction", "inbound"]],
        bubble: "Knock knock - someone is calling **+912240000000** from **+919876543210**. What should I do with this call?"
      }, {
        seg: 2,
        up: true,
        lbl: "VobizXML",
        title: "You reply with VobizXML - these are the instructions",
        desc: "The XML you return is the instruction set, and Vobiz runs it top to bottom. To hand the call to your AI agent, that XML is a Stream element pointing at your socket.",
        chips: [["<Response>"], ["<Stream bidirectional=\"true\">"], ["wss://acme.com/agent"], ["</Response>"]]
      }, {
        media: true,
        done: true,
        title: "The socket opens - audio and events both ways",
        desc: "Vobiz connects to your wss:// endpoint and the conversation begins. Caller audio arrives as media frames; your agent replies with playAudio on the same socket.",
        chips: [["media frames", "in"], ["playAudio", "out"], ["clearAudio · checkpoint"]]
      }]
    }
  }
};

<SwFlows />


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.