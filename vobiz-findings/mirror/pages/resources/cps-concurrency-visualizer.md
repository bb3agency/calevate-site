> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# CPS & Concurrency Visualizer

> Dial calls onto a live board second by second and hit both Vobiz limits yourself - CPS caps how fast you start calls, concurrency caps how many run at once. See exactly which one causes a 429.

export const CcVisualizer = () => {
  const [cps, setCps] = React.useState(3);
  const [conc, setConc] = React.useState(10);
  const [secs, setSecs] = React.useState(20);
  const [now, setNow] = React.useState(1);
  const [calls, setCalls] = React.useState([]);
  const [dialed, setDialed] = React.useState({});
  const [pending, setPending] = React.useState(0);
  const [rejC, setRejC] = React.useState(0);
  const [rejP, setRejP] = React.useState(0);
  const [bump, setBump] = React.useState({
    w: null,
    n: 0
  });
  const [cw, setCw] = React.useState(46);
  const boardRef = React.useRef(null);
  const idRef = React.useRef(0);
  const advRef = React.useRef(null);
  const bumpRef = React.useRef(null);
  const pendingRef = React.useRef(0);
  React.useEffect(() => {
    pendingRef.current = pending;
  }, [pending]);
  React.useEffect(() => () => {
    clearTimeout(advRef.current);
    clearTimeout(bumpRef.current);
  }, []);
  const busyAt = (c, s) => c.start <= s && (c.end === null || c.end >= s);
  const liveCalls = calls.filter(c => busyAt(c, now));
  const taken = new Set(liveCalls.map(c => c.ch));
  const freeList = [];
  for (let i = 0; i < conc; i++) if (!taken.has(i)) freeList.push(i);
  const used = dialed[now] || 0;
  const cpsLeft = cps - used - pending;
  const chanLeft = freeList.length - pending;
  const blk = cpsLeft <= 0 ? "C" : chanLeft <= 0 ? "P" : "";
  const remaining = Math.max(0, Math.min(cpsLeft, chanLeft));
  const ghostChans = freeList.slice(0, pending);
  React.useEffect(() => {
    const el = boardRef.current;
    if (!el) return;
    const calc = () => {
      const avail = el.clientWidth - 46;
      setCw(Math.max(28, Math.min(58, Math.floor((avail - 52) / secs))));
    };
    calc();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(calc);
    ro.observe(el);
    return () => ro.disconnect();
  }, [secs]);
  React.useEffect(() => {
    const bd = boardRef.current;
    if (!bd || bd.scrollWidth <= bd.clientWidth) return;
    const x = 52 + (now - 1) * cw;
    if (x < bd.scrollLeft + 60 || x > bd.scrollLeft + bd.clientWidth - 170) bd.scrollTo({
      left: Math.max(0, x - bd.clientWidth / 2),
      behavior: "smooth"
    });
  }, [now, cw]);
  const flash = w => {
    setBump(b => ({
      w,
      n: b.n + 1
    }));
    clearTimeout(bumpRef.current);
    bumpRef.current = setTimeout(() => setBump(b => ({
      w: null,
      n: b.n
    })), 460);
  };
  const stage = () => {
    if (cpsLeft <= 0) {
      setRejC(v => v + 1);
      flash("C");
      return;
    }
    if (chanLeft <= 0) {
      setRejP(v => v + 1);
      flash("P");
      return;
    }
    setPending(p => p + 1);
  };
  const place = () => {
    if (pending <= 0) return;
    const n = Math.min(pending, freeList.length, cps - used);
    const add = [];
    for (let i = 0; i < n; i++) add.push({
      id: ++idRef.current,
      ch: freeList[i],
      start: now,
      end: null
    });
    setCalls(cs => cs.concat(add));
    setDialed(d => Object.assign({}, d, {
      [now]: (d[now] || 0) + n
    }));
    setPending(0);
    clearTimeout(advRef.current);
    advRef.current = setTimeout(() => {
      if (pendingRef.current === 0) setNow(s => Math.min(secs, s + 1));
    }, 340);
  };
  const hangup = id => setCalls(cs => cs.map(c => c.id === id && c.end === null ? Object.assign({}, c, {
    end: now
  }) : c));
  const next = () => {
    if (pending === 0) setNow(s => Math.min(secs, s + 1));
  };
  const reset = () => {
    clearTimeout(advRef.current);
    idRef.current = 0;
    setNow(1);
    setCalls([]);
    setDialed({});
    setPending(0);
    setRejC(0);
    setRejP(0);
  };
  const resize = setter => e => {
    setter(Number(e.target.value));
    reset();
  };
  React.useEffect(() => {
    const onKey = e => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target;
      if (t && t.closest && t.closest("input,textarea,select,[contenteditable],[role=textbox]")) return;
      const k = (e.key || "").toLowerCase();
      if (k === "d" || e.key === "+") {
        e.preventDefault();
        stage();
      } else if (k === "p" || e.key === "Enter") {
        e.preventDefault();
        place();
      } else if (k === "n" || e.key === "ArrowRight") {
        e.preventDefault();
        next();
      } else if (k === "r") {
        e.preventDefault();
        reset();
      } else if (e.key === "Escape") {
        e.preventDefault();
        setPending(0);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  let tone = "mint";
  let msg;
  const plural = pending > 1;
  if (pending > 0 && remaining === 0) {
    tone = "sig";
    msg = <><b>{pending} call{plural ? "s" : ""} staged</b> — that is everything this second allows
      {cpsLeft <= 0 ? " (CPS is spent)" : " (no channel left free)"}. Press <b>Place call</b> to
      send {plural ? "them" : "it"} and move on.</>;
  } else if (pending > 0) {
    tone = "sig";
    msg = <><b>{pending} call{plural ? "s" : ""} staged.</b> Add up to {remaining} more with <b>＋</b>,
      or press <b>Place call</b> to send {plural ? "them" : "it"} and roll to the next second.</>;
  } else if (now >= secs && remaining === 0) {
    tone = "dim";
    msg = <>End of the timeline. Press <b>Reset</b> to run it again.</>;
  } else if (cpsLeft <= 0 && chanLeft <= 0) {
    tone = "red";
    msg = <><b>Both walls at once.</b> CPS is spent for this second and all {conc} channels are
      busy. Hang up a call, then advance.</>;
  } else if (cpsLeft <= 0) {
    tone = "ice";
    msg = <><b>CPS limit reached</b> — {cps} of {cps} used this second, but {chanLeft} channel
      {chanLeft === 1 ? " is" : "s are"} still free. Nothing is wrong with your capacity; you simply
      cannot start them any faster. <b>Advance a second.</b></>;
  } else if (chanLeft <= 0) {
    tone = "red";
    msg = <><b>All {conc} channels are busy</b> — you still have {cpsLeft} CPS spare this second, and
      it is worthless. <b>Hang up a call</b> (the ✕ on its head) to free a channel.</>;
  } else if (cpsLeft < chanLeft) {
    tone = "ice";
    msg = <><b>You may stage {remaining} this second.</b> CPS is the tighter wall right now — {chanLeft} channels
      are free but you may only start {cpsLeft}.</>;
  } else if (chanLeft < cpsLeft) {
    msg = <><b>You may stage {remaining} this second.</b> Concurrency is the tighter wall now — CPS would
      allow {cpsLeft}, but only {chanLeft} channel{chanLeft === 1 ? " is" : "s are"} free.</>;
  } else {
    msg = <><b>You may stage {remaining} this second.</b> Press <b>＋</b> to queue them, then
      <b> Place call</b> to send them.</>;
  }
  const BW = pending ? 150 : 136;
  const span = secs * cw;
  const btnLeft = Math.max(0, Math.min((now - 1) * cw + cw / 2 - BW / 2, span - BW));
  const rows = Array.from({
    length: conc
  }, (_, i) => conc - 1 - i);
  const cols = Array.from({
    length: secs
  }, (_, i) => i + 1);
  return <div className="cps-concurrency-visualizer not-prose">
      <div className="cc-shell">
        <p className="cc-lede">
          Every column is one <b>second</b>. Every row is one <b>channel</b>. Press <b>＋</b> to stage
          the calls you want that second, then <b>Place call</b> to send them — and watch which wall
          stops you. <b>CPS</b> caps how many you may start <i>in a second</i>; <b>concurrency</b> caps
          how many may be <i>up at once</i>.
        </p>

        <div className="cc-limits">
          {CC_LIMITS.map(L => {
    const val = L.k === "cps" ? `${used + pending}/${cps}` : `${liveCalls.length}/${conc}`;
    const hit = bump.w === (L.k === "cps" ? "C" : "P");
    return <div key={L.k} className={`cc-lim is-${L.accent}${hit ? " is-hit" : ""}`}>
                <div className="cc-lim-val">{val}</div>
                <div className="cc-lim-txt">
                  <b>{L.name}</b>
                  <span>{L.body}</span>
                </div>
                <div className="cc-lim-unit">{L.unit}</div>
              </div>;
  })}
        </div>

        <div className="cc-board" ref={boardRef}>
          <div className="cc-boardin" style={{
    "--cc-cw": `${cw}px`
  }}>
            {rows.map(ch => <div className="cc-row" key={ch}>
                <div className="cc-rowlbl">ch {ch + 1}</div>
                <div className="cc-cells">
                  {cols.map(s => <div key={s} className={`cc-cell${s === now ? " is-cur" : s < now ? " is-past" : ""}`} />)}
                  {calls.filter(c => c.ch === ch).map(c => {
    const last = c.end === null ? now : c.end;
    const isLive = c.end === null;
    return <div key={c.id} className={`cc-seg${isLive ? "" : " is-ended"}`} style={{
      left: (c.start - 1) * cw + 2,
      width: (last - c.start + 1) * cw - 4
    }} onClick={isLive ? () => hangup(c.id) : undefined} title={isLive ? `Call #${c.id} — started at second ${c.start}, still up.` : `Call #${c.id} — second ${c.start} to ${c.end}.`}>
                        {isLive ? <button type="button" className="cc-hup" title="Hang up this call" aria-label={`Hang up call ${c.id}`} onClick={e => {
      e.stopPropagation();
      hangup(c.id);
    }}>✕</button> : <span className="cc-tip">✕</span>}
                      </div>;
  })}
                  {ghostChans.indexOf(ch) > -1 && <div className="cc-ghost" style={{
    left: (now - 1) * cw + 2,
    width: cw - 4
  }} title="Staged — press Place call to send it">+</div>}
                </div>
              </div>)}

            <div className="cc-axis">
              <div className="cc-axlbl">SEC</div>
              {cols.map(s => <div key={s} className={`cc-tick${s === now ? " is-cur" : ""}`}>{s}</div>)}
            </div>

            <div className="cc-dialrow">
              <div className="cc-axlbl">DIAL</div>
              {cols.map(s => <div key={s} className={`cc-pad${s === now ? " is-cur" : s < now ? " is-done" : ""}`}>
                  {s === now ? <button type="button" key={`k${bump.n}`} className={`${blk ? `is-blk${blk} ` : ""}${bump.w ? `cc-shake${bump.w}` : ""}`} onClick={stage} title="Stage one more call for this second">{pending ? `${pending} +` : "+"}</button> : <div>{s < now ? dialed[s] || 0 : ""}</div>}
                </div>)}
            </div>

            <div className="cc-placerow">
              <div className="cc-axlbl" />
              <div className="cc-placewrap">
                <div className="cc-caret" style={{
    left: (now - 1) * cw + cw / 2
  }} />
                <button type="button" className="cc-placebtn" style={{
    left: btnLeft,
    width: BW
  }} disabled={pending === 0} onClick={place}>{pending ? `Place ${pending} call${pending > 1 ? "s" : ""}` : "Place call"}</button>
                {pending > 0 && <button type="button" className="cc-clrbtn" style={{
    left: btnLeft + BW + 8
  }} title="Clear staged calls" onClick={() => setPending(0)}>↺</button>}
              </div>
            </div>
          </div>
        </div>

        <div className={`cc-status is-${tone}`}>
          <span className="cc-dot" />
          <span className="cc-msg">{msg}</span>
          <span className="cc-acts">
            {pending > 0 && <button type="button" className="cc-abtn" onClick={() => setPending(0)}>↺ Clear staged</button>}
            <button type="button" className="cc-abtn" onClick={next} disabled={now >= secs || pending > 0}>
              Next second ▶
            </button>
            <button type="button" className="cc-abtn" onClick={reset}>↻ Reset</button>
          </span>
        </div>

        <div className="cc-stats">
          <div className="cc-st"><div className="cc-v">{now}</div><div className="cc-k">Current second</div></div>
          <div className="cc-st"><div className="cc-v is-mint">{liveCalls.length}</div><div className="cc-k">Calls up now</div></div>
          <div className="cc-st"><div className="cc-v">{calls.length}</div><div className="cc-k">Total calls initiated</div></div>
          <div className="cc-st"><div className="cc-v is-ice">{rejC}</div><div className="cc-k">Blocked by CPS</div></div>
          <div className="cc-st"><div className="cc-v is-red">{rejP}</div><div className="cc-k">Blocked by channels</div></div>
        </div>

        <div className="cc-ctl">
          <h3>Change the limits</h3>
          <div className="cc-grid3">
            <div className="cc-sl is-ice">
              <label htmlFor="cc-cps">CPS limit <span>{cps}</span></label>
              <input id="cc-cps" type="range" min="1" max="6" step="1" value={cps} onChange={e => setCps(Number(e.target.value))} />
              <small>Applies from the current second onward.</small>
            </div>
            <div className="cc-sl is-mint">
              <label htmlFor="cc-conc">Concurrency limit <span>{conc}</span></label>
              <input id="cc-conc" type="range" min="4" max="16" step="1" value={conc} onChange={resize(setConc)} />
              <small>Rebuilds the board and clears the run.</small>
            </div>
            <div className="cc-sl">
              <label htmlFor="cc-secs">Timeline <span>{secs}s</span></label>
              <input id="cc-secs" type="range" min="10" max="30" step="1" value={secs} onChange={resize(setSecs)} />
              <small>Rebuilds the board and clears the run.</small>
            </div>
          </div>
        </div>

        <div className="cc-notes">
          {CC_NOTES.map(n => <div className="cc-note" key={n.title}>
              <h4>{n.title}</h4>
              <ul>
                {n.items.map((it, i) => <li key={i} dangerouslySetInnerHTML={{
    __html: it
  }} />)}
              </ul>
            </div>)}
        </div>
      </div>
    </div>;
};

export const CC_NOTES = [{
  title: "Try this — the classic run",
  items: ["Two steps every second: press <b>＋</b> to stage the calls you want, then <b>Place call</b> to send them. The timeline rolls on by itself.", "Leave it at <b>CPS 3</b>, <b>concurrency 10</b>. Seconds 1, 2 and 3 each stage <b>3</b> and refuse a 4th — that is <b>CPS</b>, and the board is still half empty.", "Second 4 takes <b>only 1</b>. CPS still had 2 spare; you ran out of <b>channels</b>.", "Second 5 takes <b>nothing</b>. Hang up two calls with the <b>✕</b> on their head, and second 6 accepts exactly <b>2</b> — never more than you freed."]
}, {
  title: "Which wall did you hit?",
  items: ["Refused with the board half empty → <b>CPS</b>. Pace the dialer or buy CPS; more channels would sit idle.", "Refused with every row occupied → <b>concurrency</b>. Buy channels or shorten calls; more CPS only arrives at a full room faster.", "Both surface as <code>429 Too Many Requests</code> on the REST API, and a full pool also turns inbound callers away with <code>SIP 503 Service Unavailable</code>.", "Hanging up at second <i>t</i> frees the channel from <i>t+1</i> — capacity is never reusable inside the same second."]
}];

export const CC_LIMITS = [{
  k: "cps",
  accent: "ice",
  icon: "⚡",
  unit: "per second",
  name: "CPS — the doorway",
  body: "A velocity limit. Resets the moment you advance. At 1 CPS your dialer must wait 1,000 ms between calls — and still reaches 3,600 calls an hour. Low CPS is not low volume."
}, {
  k: "conc",
  accent: "mint",
  icon: "▦",
  unit: "channels",
  name: "Concurrency — the room",
  body: "A capacity limit. A channel is held for the whole call, ringing and talking alike, and frees only on hangup. Driven by how long calls last, not how fast you dial."
}];

<CcVisualizer />


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.