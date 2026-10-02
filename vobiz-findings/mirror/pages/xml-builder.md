> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Visual XML Builder – Compose Voice Call Flows

> Compose Vobiz Voice XML visually - pick verbs, reorder them, and configure attributes with a live preview. The fastest way to prototype call flows globally.

export const XmlBuilder = () => {
  const elements = [{
    id: "preanswer",
    name: "PreAnswer",
    desc: "Early media ringback"
  }, {
    id: "stream",
    name: "Stream",
    desc: "WebSocket audio"
  }, {
    id: "wait",
    name: "Wait",
    desc: "Pause call"
  }, {
    id: "play",
    name: "Play",
    desc: "Play audio file"
  }, {
    id: "speak",
    name: "Speak",
    desc: "Text-to-speech"
  }, {
    id: "gather",
    name: "Gather",
    desc: "Collect input"
  }, {
    id: "record",
    name: "Record",
    desc: "Record audio"
  }, {
    id: "dial",
    name: "Dial",
    desc: "Forward call"
  }, {
    id: "conference",
    name: "Conference",
    desc: "Join room"
  }, {
    id: "dtmf",
    name: "DTMF",
    desc: "Send tones"
  }, {
    id: "redirect",
    name: "Redirect",
    desc: "Change webhook"
  }, {
    id: "hangup",
    name: "Hangup",
    desc: "End call"
  }];
  const defaults = {
    preanswer: {
      text: "Connecting your call...",
      voice: "WOMAN",
      language: "en-US"
    },
    stream: {
      url: "wss://your-server.com/audio",
      bidirectional: true,
      keepCallAlive: true
    },
    wait: {
      length: 2,
      silence: true
    },
    play: {
      url: "https://your-server.com/welcome.mp3",
      loop: 1
    },
    speak: {
      text: "Welcome to Vobiz.",
      voice: "WOMAN",
      language: "en-US",
      loop: 1
    },
    gather: {
      actionUrl: "https://your-server.com/gather",
      method: "POST",
      numDigits: 1,
      timeout: 5,
      finishOnKey: "#",
      promptText: "Press 1 for sales, 2 for support."
    },
    record: {
      actionUrl: "https://your-server.com/record",
      maxLength: 60,
      playBeep: true,
      finishOnKey: "#"
    },
    dial: {
      number: "+919876543210",
      callerId: "",
      actionUrl: "",
      method: "POST",
      redirect: true,
      timeout: 30
    },
    conference: {
      name: "MyRoom",
      startOnEnter: true,
      endOnExit: false,
      maxMembers: 10
    },
    dtmf: {
      digits: "1234"
    },
    redirect: {
      url: "https://your-server.com/next.xml",
      method: "POST"
    },
    hangup: {
      reason: ""
    }
  };
  const nameOf = id => {
    const e = elements.find(x => x.id === id);
    return e ? e.name : id;
  };
  const [selected, setSelected] = React.useState(["speak"]);
  const [configs, setConfigs] = React.useState({
    speak: Object.assign({}, defaults.speak)
  });
  const [copied, setCopied] = React.useState(false);
  const [dragOver, setDragOver] = React.useState(-1);
  const dragSrc = React.useRef(-1);
  const toggle = id => {
    if (selected.indexOf(id) >= 0) {
      setSelected(selected.filter(x => x !== id));
    } else {
      setSelected(selected.concat([id]));
      if (!configs[id]) setConfigs(Object.assign({}, configs, {
        [id]: Object.assign({}, defaults[id])
      }));
    }
  };
  const update = (id, patch) => {
    const cur = configs[id] || defaults[id];
    setConfigs(Object.assign({}, configs, {
      [id]: Object.assign({}, cur, patch)
    }));
  };
  const move = (from, to) => {
    if (to < 0 || to >= selected.length) return;
    const arr = selected.slice();
    const item = arr.splice(from, 1)[0];
    arr.splice(to, 0, item);
    setSelected(arr);
  };
  const removeAt = id => setSelected(selected.filter(x => x !== id));
  const xmlEsc = s => {
    return String(s == null ? "" : s).split("&").join("&amp;").split('"').join("&quot;").split("<").join("&lt;").split(">").join("&gt;");
  };
  const buildXml = () => {
    const lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<Response>"];
    for (let k = 0; k < selected.length; k++) {
      const id = selected[k];
      const c = configs[id] || defaults[id];
      if (id === "preanswer") {
        lines.push("  <PreAnswer>");
        lines.push("    <Speak voice=\"" + c.voice + "\" language=\"" + c.language + "\">" + xmlEsc(c.text) + "</Speak>");
        lines.push("  </PreAnswer>");
      } else if (id === "speak") {
        lines.push("  <Speak voice=\"" + c.voice + "\" language=\"" + c.language + "\" loop=\"" + c.loop + "\">" + xmlEsc(c.text) + "</Speak>");
      } else if (id === "play") {
        lines.push("  <Play loop=\"" + c.loop + "\">" + xmlEsc(c.url) + "</Play>");
      } else if (id === "wait") {
        lines.push("  <Wait length=\"" + c.length + "\" silence=\"" + c.silence + "\"/>");
      } else if (id === "stream") {
        lines.push("  <Stream bidirectional=\"" + c.bidirectional + "\" keepCallAlive=\"" + c.keepCallAlive + "\">" + xmlEsc(c.url) + "</Stream>");
      } else if (id === "gather") {
        lines.push("  <Gather action=\"" + xmlEsc(c.actionUrl) + "\" method=\"" + c.method + "\" numDigits=\"" + c.numDigits + "\" executionTimeout=\"" + c.timeout + "\" finishOnKey=\"" + c.finishOnKey + "\">");
        lines.push("    <Speak>" + xmlEsc(c.promptText) + "</Speak>");
        lines.push("  </Gather>");
      } else if (id === "record") {
        lines.push("  <Record action=\"" + xmlEsc(c.actionUrl) + "\" maxLength=\"" + c.maxLength + "\" playBeep=\"" + c.playBeep + "\" finishOnKey=\"" + c.finishOnKey + "\"/>");
      } else if (id === "dial") {
        const attrs = ["timeout=\"" + c.timeout + "\"", "redirect=\"" + c.redirect + "\""];
        if (c.callerId) attrs.push("callerId=\"" + xmlEsc(c.callerId) + "\"");
        if (c.actionUrl) {
          attrs.push("action=\"" + xmlEsc(c.actionUrl) + "\"");
          attrs.push("method=\"" + c.method + "\"");
        }
        lines.push("  <Dial " + attrs.join(" ") + ">");
        lines.push("    <Number>" + xmlEsc(c.number) + "</Number>");
        lines.push("  </Dial>");
      } else if (id === "conference") {
        lines.push("  <Conference startConferenceOnEnter=\"" + c.startOnEnter + "\" endConferenceOnExit=\"" + c.endOnExit + "\" maxMembers=\"" + c.maxMembers + "\">" + xmlEsc(c.name) + "</Conference>");
      } else if (id === "dtmf") {
        lines.push("  <DTMF>" + xmlEsc(c.digits) + "</DTMF>");
      } else if (id === "redirect") {
        lines.push("  <Redirect method=\"" + c.method + "\">" + xmlEsc(c.url) + "</Redirect>");
      } else if (id === "hangup") {
        if (c.reason) lines.push("  <Hangup reason=\"" + c.reason + "\"/>"); else lines.push("  <Hangup/>");
      }
    }
    lines.push("</Response>");
    return lines.join("\n");
  };
  const xml = buildXml();
  const onCopy = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(xml);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const onDragStart = i => e => {
    dragSrc.current = i;
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = "move";
      try {
        e.dataTransfer.setData("text/plain", String(i));
      } catch (_) {}
    }
  };
  const onDragOver = i => e => {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
    if (dragOver !== i) setDragOver(i);
  };
  const onDragLeave = () => setDragOver(-1);
  const onDrop = i => e => {
    e.preventDefault();
    const from = dragSrc.current;
    setDragOver(-1);
    dragSrc.current = -1;
    if (from < 0 || from === i) return;
    move(from, i);
  };
  const inputCls = "w-full px-3 py-2 bg-transparent border border-gray-200 dark:border-white/10 rounded-lg text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary text-sm transition";
  const labelCls = "block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5";
  const renderFields = id => {
    const c = configs[id] || defaults[id];
    const set = patch => update(id, patch);
    if (id === "preanswer") {
      return <div className="space-y-3">
          <div>
            <label className={labelCls}>Ringback message</label>
            <textarea rows={2} value={c.text} onChange={e => set({
        text: e.target.value
      })} className={inputCls} />
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Voice</label>
              <select value={c.voice} onChange={e => set({
        voice: e.target.value
      })} className={inputCls}>
                <option value="WOMAN">Woman</option>
                <option value="MAN">Man</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Language</label>
              <select value={c.language} onChange={e => set({
        language: e.target.value
      })} className={inputCls}>
                <option value="en-US">English (US)</option>
                <option value="en-IN">English (India)</option>
                <option value="hi-IN">Hindi</option>
              </select>
            </div>
          </div>
        </div>;
    }
    if (id === "speak") {
      return <div className="space-y-3">
          <div>
            <label className={labelCls}>Text to Speak</label>
            <textarea rows={2} value={c.text} onChange={e => set({
        text: e.target.value
      })} className={inputCls} />
          </div>
          <div className="grid sm:grid-cols-3 gap-3">
            <div>
              <label className={labelCls}>Voice</label>
              <select value={c.voice} onChange={e => set({
        voice: e.target.value
      })} className={inputCls}>
                <option value="WOMAN">Woman</option>
                <option value="MAN">Man</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Language</label>
              <select value={c.language} onChange={e => set({
        language: e.target.value
      })} className={inputCls}>
                <option value="en-US">English (US)</option>
                <option value="en-GB">English (UK)</option>
                <option value="en-IN">English (IN)</option>
                <option value="hi-IN">Hindi</option>
                <option value="es-ES">Spanish</option>
                <option value="fr-FR">French</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Loop</label>
              <input type="number" min="1" max="10" value={c.loop} onChange={e => set({
        loop: e.target.value
      })} className={inputCls} />
            </div>
          </div>
        </div>;
    }
    if (id === "play") {
      return <div className="grid sm:grid-cols-4 gap-3">
          <div className="sm:col-span-3">
            <label className={labelCls}>Audio URL (.mp3 / .wav)</label>
            <input value={c.url} onChange={e => set({
        url: e.target.value
      })} className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>Loop</label>
            <input type="number" min="1" max="10" value={c.loop} onChange={e => set({
        loop: e.target.value
      })} className={inputCls} />
          </div>
        </div>;
    }
    if (id === "wait") {
      return <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>Length (sec)</label>
            <input type="number" min="1" max="120" value={c.length} onChange={e => set({
        length: e.target.value
      })} className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>Silence</label>
            <select value={String(c.silence)} onChange={e => set({
        silence: e.target.value === "true"
      })} className={inputCls}>
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          </div>
        </div>;
    }
    if (id === "stream") {
      return <div className="space-y-3">
          <div>
            <label className={labelCls}>WebSocket URL (wss://)</label>
            <input value={c.url} onChange={e => set({
        url: e.target.value
      })} className={inputCls} />
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Bidirectional</label>
              <select value={String(c.bidirectional)} onChange={e => set({
        bidirectional: e.target.value === "true"
      })} className={inputCls}>
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Keep call alive</label>
              <select value={String(c.keepCallAlive)} onChange={e => set({
        keepCallAlive: e.target.value === "true"
      })} className={inputCls}>
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            </div>
          </div>
        </div>;
    }
    if (id === "gather") {
      return <div className="space-y-3">
          <div>
            <label className={labelCls}>Prompt (nested Speak)</label>
            <textarea rows={2} value={c.promptText} onChange={e => set({
        promptText: e.target.value
      })} className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>Action URL</label>
            <input value={c.actionUrl} onChange={e => set({
        actionUrl: e.target.value
      })} className={inputCls} />
          </div>
          <div className="grid sm:grid-cols-4 gap-3">
            <div>
              <label className={labelCls}>Method</label>
              <select value={c.method} onChange={e => set({
        method: e.target.value
      })} className={inputCls}>
                <option value="POST">POST</option>
                <option value="GET">GET</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Digits</label>
              <input type="number" min="1" max="20" value={c.numDigits} onChange={e => set({
        numDigits: e.target.value
      })} className={inputCls} />
            </div>
            <div>
              <label className={labelCls}>Timeout (s)</label>
              <input type="number" min="1" max="60" value={c.timeout} onChange={e => set({
        timeout: e.target.value
      })} className={inputCls} />
            </div>
            <div>
              <label className={labelCls}>Finish key</label>
              <input value={c.finishOnKey} onChange={e => set({
        finishOnKey: e.target.value
      })} className={inputCls} />
            </div>
          </div>
        </div>;
    }
    if (id === "record") {
      return <div className="space-y-3">
          <div>
            <label className={labelCls}>Action URL (recording webhook)</label>
            <input value={c.actionUrl} onChange={e => set({
        actionUrl: e.target.value
      })} className={inputCls} />
          </div>
          <div className="grid sm:grid-cols-3 gap-3">
            <div>
              <label className={labelCls}>Max length (s)</label>
              <input type="number" min="1" max="3600" value={c.maxLength} onChange={e => set({
        maxLength: e.target.value
      })} className={inputCls} />
            </div>
            <div>
              <label className={labelCls}>Play beep</label>
              <select value={String(c.playBeep)} onChange={e => set({
        playBeep: e.target.value === "true"
      })} className={inputCls}>
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Finish key</label>
              <input value={c.finishOnKey} onChange={e => set({
        finishOnKey: e.target.value
      })} className={inputCls} />
            </div>
          </div>
        </div>;
    }
    if (id === "dial") {
      return <div className="space-y-3">
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Phone Number</label>
              <input value={c.number} onChange={e => set({
        number: e.target.value
      })} className={inputCls} />
            </div>
            <div>
              <label className={labelCls}>Caller ID (owned/authorized)</label>
              <input value={c.callerId} onChange={e => set({
        callerId: e.target.value
      })} className={inputCls} />
            </div>
          </div>
          <div>
            <label className={labelCls}>Action URL (Opt)</label>
            <input value={c.actionUrl} onChange={e => set({
        actionUrl: e.target.value
      })} className={inputCls} />
          </div>
          <div className="grid sm:grid-cols-3 gap-3">
            <div>
              <label className={labelCls}>Method</label>
              <select value={c.method} onChange={e => set({
        method: e.target.value
      })} className={inputCls}>
                <option value="POST">POST</option>
                <option value="GET">GET</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Execute action XML?</label>
              <select value={String(c.redirect)} onChange={e => set({
        redirect: e.target.value === "true"
      })} className={inputCls}>
                <option value="true">True</option>
                <option value="false">False</option>
              </select>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">False still sends the final result to the action URL.</p>
            </div>
            <div>
              <label className={labelCls}>Timeout (s)</label>
              <input type="number" min="1" value={c.timeout} onChange={e => set({
        timeout: e.target.value
      })} className={inputCls} />
            </div>
          </div>
        </div>;
    }
    if (id === "conference") {
      return <div className="space-y-3">
          <div>
            <label className={labelCls}>Room name</label>
            <input value={c.name} onChange={e => set({
        name: e.target.value
      })} className={inputCls} />
          </div>
          <div className="grid sm:grid-cols-3 gap-3">
            <div>
              <label className={labelCls}>Start on enter</label>
              <select value={String(c.startOnEnter)} onChange={e => set({
        startOnEnter: e.target.value === "true"
      })} className={inputCls}>
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>End on exit</label>
              <select value={String(c.endOnExit)} onChange={e => set({
        endOnExit: e.target.value === "true"
      })} className={inputCls}>
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Max members</label>
              <input type="number" min="2" max="100" value={c.maxMembers} onChange={e => set({
        maxMembers: e.target.value
      })} className={inputCls} />
            </div>
          </div>
        </div>;
    }
    if (id === "dtmf") {
      return <div>
          <label className={labelCls}>Tones (digits / # / *)</label>
          <input value={c.digits} onChange={e => set({
        digits: e.target.value
      })} className={inputCls} />
        </div>;
    }
    if (id === "redirect") {
      return <div className="grid sm:grid-cols-4 gap-3">
          <div className="sm:col-span-3">
            <label className={labelCls}>Target URL</label>
            <input value={c.url} onChange={e => set({
        url: e.target.value
      })} className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>Method</label>
            <select value={c.method} onChange={e => set({
        method: e.target.value
      })} className={inputCls}>
              <option value="POST">POST</option>
              <option value="GET">GET</option>
            </select>
          </div>
        </div>;
    }
    if (id === "hangup") {
      return <div>
          <label className={labelCls}>Reason (optional)</label>
          <select value={c.reason} onChange={e => set({
        reason: e.target.value
      })} className={inputCls}>
            <option value="">— none —</option>
            <option value="rejected">rejected</option>
            <option value="busy">busy</option>
          </select>
        </div>;
    }
    return null;
  };
  const cards = [];
  for (let i = 0; i < selected.length; i++) {
    const id = selected[i];
    const isOver = dragOver === i;
    const borderCls = isOver ? "border-primary/60 ring-2 ring-primary/20" : "border-gray-200 dark:border-white/10";
    cards.push(<div key={"card-" + id} draggable onDragStart={onDragStart(i)} onDragOver={onDragOver(i)} onDragLeave={onDragLeave} onDrop={onDrop(i)} className={"rounded-2xl border bg-white dark:bg-zinc-900 transition " + borderCls}>
        <div className="flex items-stretch">
          <div className="flex flex-col items-center justify-center gap-1 px-2 py-3 border-r border-gray-100 dark:border-white/5 text-gray-400">
            <button type="button" onClick={() => move(i, i - 1)} disabled={i === 0} className="w-6 h-6 inline-flex items-center justify-center rounded-md hover:text-primary hover:bg-primary/5 disabled:opacity-30 transition" aria-label="Move up">↑</button>
            <span className="cursor-grab text-base leading-none select-none" title="Drag to reorder">≡</span>
            <button type="button" onClick={() => move(i, i + 1)} disabled={i === selected.length - 1} className="w-6 h-6 inline-flex items-center justify-center rounded-md hover:text-primary hover:bg-primary/5 disabled:opacity-30 transition" aria-label="Move down">↓</button>
          </div>
          <div className="flex-1 p-4 min-w-0">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-primary/10 text-primary dark:text-primary-light text-[10px] font-semibold">{i + 1}</span>
                <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{nameOf(id)} Configuration</span>
              </div>
              <button type="button" onClick={() => removeAt(id)} className="w-6 h-6 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-red-500 hover:bg-red-500/5 transition" aria-label={"Remove " + nameOf(id)}>×</button>
            </div>
            {renderFields(id)}
          </div>
        </div>
      </div>);
    if (i < selected.length - 1) {
      cards.push(<div key={"conn-" + id} className="flex justify-center py-1 text-primary/50" aria-hidden="true">
          <span className="text-xs leading-none">↓</span>
        </div>);
    }
  }
  return <div className="my-6 not-prose space-y-4">
      <div className="rounded-2xl border border-gray-200 dark:border-white/10 bg-white dark:bg-zinc-900 p-5">
        <div className="flex items-center gap-2 mb-4">
          <span className="text-base leading-none">⚙</span>
          <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">Elements to Include</div>
          {selected.length > 0 ? <span className="ml-auto text-xs text-gray-500 dark:text-gray-400">{selected.length} selected</span> : null}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
          {elements.map(el => {
    const active = selected.indexOf(el.id) >= 0;
    const tileCls = active ? "text-left rounded-xl border px-3 py-2.5 transition select-none border-primary/50 bg-primary/10 ring-1 ring-primary/30" : "text-left rounded-xl border px-3 py-2.5 transition select-none border-gray-200 dark:border-white/10 bg-white dark:bg-zinc-900 hover:border-gray-300 dark:hover:border-white/20";
    const nameCls = active ? "text-sm font-semibold leading-tight text-primary dark:text-primary-light" : "text-sm font-semibold leading-tight text-gray-900 dark:text-gray-100";
    const boxCls = active ? "inline-flex items-center justify-center w-4 h-4 rounded border flex-shrink-0 mt-0.5 transition bg-primary border-primary text-white text-[10px] leading-none" : "inline-flex items-center justify-center w-4 h-4 rounded border flex-shrink-0 mt-0.5 transition border-gray-300 dark:border-white/20 bg-transparent";
    return <button key={el.id} type="button" onClick={() => toggle(el.id)} className={tileCls}>
                <div className="flex items-start gap-2">
                  <span className={boxCls}>{active ? "✓" : ""}</span>
                  <div>
                    <div className={nameCls}>{el.name}</div>
                    <div className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5 leading-tight">{el.desc}</div>
                  </div>
                </div>
              </button>;
  })}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4 items-start">
        <div className="space-y-1">
          {selected.length === 0 ? <div className="rounded-2xl border border-dashed border-gray-300 dark:border-white/10 bg-white/40 dark:bg-zinc-900/50 p-8 text-center text-sm text-gray-500 dark:text-gray-400">
              Select one or more elements above to configure them here.
            </div> : cards}
        </div>

        <div className="lg:sticky lg:top-24">
          <div className="rounded-2xl border border-gray-200 dark:border-white/10 bg-gray-900 dark:bg-black/40 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/10">
              <div className="flex items-center gap-2 text-xs text-gray-400 font-mono">
                <span className="w-2 h-2 rounded-full bg-red-400/70"></span>
                <span className="w-2 h-2 rounded-full bg-yellow-400/70"></span>
                <span className="w-2 h-2 rounded-full bg-green-400/70"></span>
                <span className="ml-2">response.xml</span>
              </div>
              <button type="button" onClick={onCopy} className="text-xs px-2.5 py-1 rounded-md border border-white/10 hover:border-primary/40 hover:text-primary text-gray-300 transition">
                {copied ? "✓ Copied" : "Copy"}
              </button>
            </div>
            <pre className="text-xs leading-relaxed font-mono text-gray-100 p-4 overflow-auto whitespace-pre min-h-[280px] max-h-[520px]"><code>{xml}</code></pre>
          </div>
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-3">
            Return this XML from your webhook with header{" "}
            <span className="font-mono text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-white/[0.06] px-1.5 py-0.5 rounded">Content-Type: application/xml</span>
          </div>
        </div>
      </div>
    </div>;
};

Select the verbs you need, order them with drag-and-drop or the up/down arrows, configure each one, and copy the generated XML. The output updates live. Use the visual builder to prototype a call flow quickly or to understand element nesting rules. For production apps, export the XML and serve it from your Answer URL. See the [Voice XML overview](/docs/xml/overview) for the full attribute reference.

<XmlBuilder />

## What XML does

Vobiz Voice XML controls the flow of a call. When a call comes in, Vobiz hits your webhook (`answer_url`) and expects an XML response describing what to do - speak text, play audio, gather digits, dial out, record, etc. See [How XML Works](/docs/xml/overview/how-it-works).

## When to use this builder

* **Prototyping** - sketch a call flow visually, then drop the XML into your webhook handler.
* **Learning the schema** - see valid attribute combinations for each element.
* **Generating boilerplate** - start from a working IVR / voicemail / dial template instead of from scratch.

## Where to put the XML

Your webhook handler returns this XML in the response body with `Content-Type: application/xml`. Example in Python (Flask):

```python theme={null}
from flask import Flask, Response

app = Flask(__name__)

@app.route("/answer", methods=["POST"])
def answer():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Speak voice="WOMAN" language="en-US">Welcome to Vobiz.</Speak>
  <Hangup/>
</Response>"""
    return Response(xml, mimetype="application/xml")
```

## Related

<Columns cols={2}>
  <Card title="How XML Works" icon="book-open" href="/docs/xml/overview/how-it-works">
    The request/response flow Vobiz uses to drive call control.
  </Card>

  <Card title="Getting Started with XML" icon="rocket" href="/docs/xml/overview/getting-started">
    Set up your first webhook and return your first XML response.
  </Card>

  <Card title="XML Best Practices" icon="star" href="/docs/xml/overview/best-practices">
    Patterns for performance, error handling, and maintainability.
  </Card>

  <Card title="The Response Element" icon="file-code" href="/docs/xml/response">
    Reference: every XML must be wrapped in `<Response>`.
  </Card>
</Columns>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.