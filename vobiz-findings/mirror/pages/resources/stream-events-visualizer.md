> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stream Events Visualizer

> Step through the Vobiz bidirectional Stream WebSocket lifecycle and inspect start, media, playback, checkpoint, barge-in, and stop events.

export const StreamEventsVisualizer = () => {
  const [currentIndex, setCurrentIndex] = React.useState(0);
  const [delivered, setDelivered] = React.useState([]);
  const [activeIndex, setActiveIndex] = React.useState(null);
  const [isAnimating, setIsAnimating] = React.useState(false);
  const timerRef = React.useRef(null);
  const nextStep = STREAM_FLOW[currentIndex];
  const activeStep = activeIndex === null ? null : STREAM_FLOW[activeIndex];
  const isComplete = currentIndex >= STREAM_FLOW.length;
  React.useEffect(() => () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
  }, []);
  const receivedByApp = React.useMemo(() => {
    const index = [...delivered].reverse().find(item => STREAM_FLOW[item].receiver === "app");
    return index === undefined ? null : STREAM_FLOW[index];
  }, [delivered]);
  const receivedByVobiz = React.useMemo(() => {
    const index = [...delivered].reverse().find(item => STREAM_FLOW[item].receiver === "vobiz");
    return index === undefined ? null : STREAM_FLOW[index];
  }, [delivered]);
  const visibleHistory = delivered.slice(-5).map(index => ({
    index,
    step: STREAM_FLOW[index]
  }));
  const hiddenHistoryCount = Math.max(0, delivered.length - visibleHistory.length);
  const connectionState = delivered.includes(STREAM_FLOW.length - 1) ? "closed" : delivered.includes(STREAM_FLOW.length - 2) ? "stopping" : delivered.includes(0) ? "connected" : "waiting";
  const runNext = actor => {
    if (!nextStep || nextStep.sender !== actor || isAnimating) return;
    const stepIndex = currentIndex;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    setActiveIndex(stepIndex);
    setIsAnimating(true);
    timerRef.current = window.setTimeout(() => {
      setDelivered(items => [...items, stepIndex]);
      setCurrentIndex(index => index + 1);
      setActiveIndex(null);
      setIsAnimating(false);
      timerRef.current = null;
    }, reduceMotion ? 60 : 760);
  };
  const replay = () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    setCurrentIndex(0);
    setDelivered([]);
    setActiveIndex(null);
    setIsAnimating(false);
  };
  const actorButton = actor => {
    const isTurn = nextStep?.sender === actor;
    const otherActor = actor === "vobiz" ? "Application" : "Vobiz";
    const label = isComplete ? "Flow complete" : isTurn ? nextStep.buttonLabel : `Waiting for ${otherActor}`;
    return <button type="button" className={`sev-send-button ${isTurn ? "is-ready" : ""}`} onClick={() => runNext(actor)} disabled={!isTurn || isAnimating}>
        <span className="sev-button-signal" aria-hidden="true">{isTurn ? "●" : "○"}</span>
        <span>{label}</span>
        <span aria-hidden="true">{isTurn ? actor === "vobiz" ? "→" : "←" : ""}</span>
      </button>;
  };
  const railDirection = activeStep?.sender === "app" || !activeStep && nextStep?.sender === "app" ? "app-to-vobiz" : "vobiz-to-app";
  return <div className="stream-events-visualizer not-prose">
      <main className="sev-shell">
        <section className="sev-intro">
          <div>
            <p className="sev-eyebrow">Interactive WebSocket sequence</p>
            <h1>See every Stream event move between Vobiz and your application.</h1>
            <p className="sev-lede">
              Click the highlighted sender. Follow each JSON packet across the WebSocket, inspect what the receiver gets, and see how barge-in and stream shutdown behave.
            </p>
          </div>
          <div className="sev-prerequisites" aria-label="Stream prerequisites">
            <span>✓ bidirectional="true"</span>
            <span>✓ Active WSS</span>
            <span>✓ JSON messages</span>
          </div>
        </section>

        <section className="sev-workbench" aria-label="Interactive Stream event sequence">
          <div className="sev-progress-strip">
            <div className="sev-progress-copy">
              <span>{isComplete ? "Sequence complete" : `Next step ${currentIndex + 1}`}</span>
              <strong>{delivered.length} of {STREAM_FLOW.length} delivered</strong>
            </div>
            <div className="sev-progress-track" role="progressbar" aria-label="Sequence progress" aria-valuemin="0" aria-valuemax={STREAM_FLOW.length} aria-valuenow={delivered.length}>
              <div className="sev-progress-value" style={{
    width: `${delivered.length / STREAM_FLOW.length * 100}%`
  }} />
            </div>
          </div>

          <div className="sev-workbench-grid">
            <article className="sev-actor sev-actor-vobiz">
              <div className="sev-actor-heading">
                <div className="sev-actor-icon sev-vobiz-icon" aria-hidden="true">
                  <img src="/docs/docs/favicon.svg" alt="" />
                </div>
                <div><span>Telephony platform</span><h2>Vobiz</h2></div>
              </div>
              <p className="sev-actor-description">Opens the stream, sends caller audio, plays queued audio, and acknowledges commands.</p>
              {actorButton("vobiz")}
              <div className="sev-inbox-label">↳ Last command received</div>
              <EventPayload step={receivedByVobiz} empty="The application has not sent a command yet." />
            </article>

            <section className="sev-sequence-lane" aria-label="WebSocket event lane">
              <div className="sev-lane-heading">
                <strong>WSS · bidirectional</strong>
                <span>Audio + JSON events</span>
              </div>

              <div className="sev-live-rail" data-direction={railDirection}>
                <span className="sev-rail-endpoint">V</span>
                <div className="sev-rail-line" />
                <span className="sev-rail-endpoint">A</span>
                {isAnimating && activeStep && <div className={`sev-moving-packet is-${railDirection}`}>{activeStep.event}</div>}
              </div>

              <div className="sev-current-cue" aria-live="polite">
                <div className={`sev-cue-icon ${isComplete ? "is-complete" : ""}`} aria-hidden="true">{isComplete ? "✓" : currentIndex + 1}</div>
                {isComplete ? <div>
                    <span>Sequence complete</span>
                    <h2>The WebSocket close is the end-of-stream signal.</h2>
                    <p>No inbound <code>{`{ "event": "stop" }`}</code> packet is expected.</p>
                    <button type="button" className="sev-replay-button" onClick={replay}>↻ Replay from start</button>
                  </div> : <div>
                    <span>Next · click {ACTOR_LABEL[nextStep.sender]}</span>
                    <h2>{nextStep.title}</h2>
                    <p>{nextStep.description}</p>
                  </div>}
              </div>

              <div className="sev-history-heading">
                <span>Sequence history</span>
                <span>{delivered.length} delivered</span>
              </div>
              <div className="sev-history" aria-label="Delivered event history">
                {hiddenHistoryCount > 0 && <div className="sev-earlier-events">+ {hiddenHistoryCount} earlier events</div>}
                {visibleHistory.length === 0 ? <div className="sev-history-empty">The first start event will appear here.</div> : visibleHistory.map(({index, step}) => <div key={step.id} className={`sev-history-row is-${step.sender}`}>
                    <span className="sev-history-number">{String(index + 1).padStart(2, "0")}</span>
                    <span>{ACTOR_LABEL[step.sender]}</span>
                    <span className="sev-history-arrow" aria-hidden="true">{step.sender === "vobiz" ? "→" : "←"}</span>
                    <strong>{step.event}</strong>
                    <span className="sev-history-receiver">{ACTOR_LABEL[step.receiver]}</span>
                  </div>)}
              </div>
            </section>

            <article className="sev-actor sev-actor-app">
              <div className="sev-actor-heading">
                <div className="sev-actor-icon" aria-hidden="true">A</div>
                <div><span>Your WebSocket server</span><h2>Application</h2></div>
              </div>
              <p className="sev-actor-description">Processes inbound media, queues agent audio, checkpoints utterances, and handles barge-in.</p>
              {actorButton("app")}
              <div className="sev-inbox-label">↳ Application inbox</div>
              <EventPayload step={receivedByApp} empty="Click Vobiz to receive the start payload." />
            </article>
          </div>
        </section>

        <section className="sev-rules" aria-label="Important Stream event rules">
          <div><strong>media</strong><span>Inbound frames arrive about 50 times per second.</span></div>
          <div><strong>playedStream</strong><span>Only arrives after uninterrupted playback.</span></div>
          <div><strong>checkpoint</strong><span>Names the utterance being tracked.</span></div>
          <div><strong>stop</strong><span>Has no inbound JSON acknowledgment.</span></div>
        </section>

        <div className="sev-footer-link">
          <a href="/docs/xml/stream/stream-events">Read the Stream Events reference <span aria-hidden="true">→</span></a>
        </div>
      </main>
    </div>;
};

export const STREAM_ID = "c4dfd815-a92a-4140-ab85-5ff28c004116";

export const STREAM_FLOW = [{
  id: "start",
  event: "start",
  sender: "vobiz",
  receiver: "app",
  buttonLabel: "Open stream and send start",
  title: "Vobiz establishes the stream",
  description: "The start event arrives once. Store start.streamId and use start.mediaFormat to decode inbound media.",
  payload: {
    sequenceNumber: 0,
    event: "start",
    start: {
      callId: "5401fd2e-6344-40df-a22c-c8ffea7a92e7",
      streamId: STREAM_ID,
      accountId: "500025",
      tracks: ["inbound"],
      mediaFormat: {
        encoding: "audio/x-l16",
        sampleRate: 8000
      }
    },
    extra_headers: "{}"
  }
}, ...[1, 2, 3].map(chunk => ({
  id: `greeting-chunk-${chunk}`,
  event: "playAudio",
  sender: "app",
  receiver: "vobiz",
  buttonLabel: `Send greeting chunk ${chunk} of 3`,
  title: `The application queues greeting chunk ${chunk}`,
  description: "Outbound playback declares its own supported format. Small chunks keep interruption responsive.",
  payload: {
    event: "playAudio",
    streamId: STREAM_ID,
    media: {
      contentType: "audio/x-mulaw",
      sampleRate: 8000,
      payload: `<base64-greeting-chunk-${String(chunk).padStart(3, "0")}>`
    }
  }
})), {
  id: "greeting-checkpoint",
  event: "checkpoint",
  sender: "app",
  receiver: "vobiz",
  buttonLabel: "Mark the greeting checkpoint",
  title: "The application marks the utterance boundary",
  description: "Send the checkpoint after the final audio chunk. Its unique name identifies a future playback acknowledgment.",
  payload: {
    event: "checkpoint",
    streamId: STREAM_ID,
    name: "greeting-complete"
  }
}, {
  id: "caller-media",
  event: "media",
  sender: "vobiz",
  receiver: "app",
  buttonLabel: "Deliver a caller media frame",
  title: "The caller interrupts the greeting",
  description: "Voice activity is detected while greeting audio remains queued. Inbound media uses the format from start.mediaFormat.",
  payload: {
    sequenceNumber: 2,
    streamId: STREAM_ID,
    event: "media",
    media: {
      track: "inbound",
      timestamp: "1778597597091",
      chunk: 2,
      payload: "<base64-user-audio>"
    },
    extra_headers: "{}"
  }
}, {
  id: "barge-in-clear",
  event: "clearAudio",
  sender: "app",
  receiver: "vobiz",
  buttonLabel: "Clear queued audio",
  title: "The application handles barge-in",
  description: "Send clearAudio as soon as speech is detected. The interrupted greeting checkpoint will not emit playedStream.",
  payload: {
    event: "clearAudio",
    streamId: STREAM_ID
  }
}, {
  id: "barge-in-cleared",
  event: "clearedAudio",
  sender: "vobiz",
  receiver: "app",
  buttonLabel: "Confirm the queue was cleared",
  title: "Vobiz acknowledges the interruption",
  description: "The pending playback queue is empty. The application can now send audio for the caller's new request.",
  payload: {
    sequenceNumber: 3,
    event: "clearedAudio",
    streamId: STREAM_ID
  }
}, {
  id: "new-response",
  event: "playAudio",
  sender: "app",
  receiver: "vobiz",
  buttonLabel: "Send the new response",
  title: "The application queues a fresh response",
  description: "The new response uses the same streamId and declares the format of its outbound audio payload.",
  payload: {
    event: "playAudio",
    streamId: STREAM_ID,
    media: {
      contentType: "audio/x-mulaw",
      sampleRate: 8000,
      payload: "<base64-new-response>"
    }
  }
}, {
  id: "response-checkpoint",
  event: "checkpoint",
  sender: "app",
  receiver: "vobiz",
  buttonLabel: "Checkpoint the new response",
  title: "The application tracks the new response",
  description: "A unique checkpoint name lets the application identify which utterance eventually finishes playing.",
  payload: {
    event: "checkpoint",
    streamId: STREAM_ID,
    name: "response-3"
  }
}, {
  id: "response-played",
  event: "playedStream",
  sender: "vobiz",
  receiver: "app",
  buttonLabel: "Acknowledge completed playback",
  title: "Vobiz confirms the response was played",
  description: "The checkpoint completed without interruption. playedStream echoes its name and does not include streamId.",
  payload: {
    event: "playedStream",
    name: "response-3"
  }
}, {
  id: "stop",
  event: "stop",
  sender: "app",
  receiver: "vobiz",
  buttonLabel: "Stop the stream",
  title: "The application ends the stream",
  description: "Vobiz stops streaming immediately and continues with the next XML element when one exists.",
  payload: {
    event: "stop",
    streamId: STREAM_ID
  }
}, {
  id: "socket-close",
  event: "WebSocket close",
  sender: "vobiz",
  receiver: "app",
  buttonLabel: "Close the WebSocket",
  title: "The WebSocket closes without a stop event",
  description: "The close frame is the canonical end-of-stream signal. Vobiz does not send an inbound JSON stop event.",
  payload: {
    transport: "WebSocket close frame",
    state: "closed",
    note: "Transport signal, not an inbound Vobiz JSON event"
  },
  transportSignal: true
}];

export const EventPayload = ({step, empty}) => <div className="sev-payload">
    <div className="sev-payload-heading">
      <span aria-hidden="true">{`{ }`}</span>
      <span>{step ? step.transportSignal ? "Transport signal" : `${step.event} payload` : "Waiting"}</span>
    </div>
    {step ? <pre tabIndex="0"><code>{JSON.stringify(step.payload, null, 2)}</code></pre> : <div className="sev-empty-payload">{empty}</div>}
  </div>;

export const ACTOR_LABEL = {
  vobiz: "Vobiz",
  app: "Application"
};

<StreamEventsVisualizer />


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.