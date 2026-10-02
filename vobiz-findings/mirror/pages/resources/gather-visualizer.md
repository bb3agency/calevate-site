> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Gather XML Input Visualizer

> Walk a Gather from prompt to action URL. Press the dial pad, watch which of the four terminators wins - numDigits, finishOnKey, digitEndTimeout or executionTimeout - and read the XML and webhook at every step.

export const GV_CALL = "6f1d4a92-3b77-4d0e-9f2a-1c8b5e7d0431";

export const GV_XML = {
  gather: `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather action="https://you.example/gather" method="POST"
          inputType="dtmf speech"
          numDigits="4"
          finishOnKey="#"
          digitEndTimeout="3"
          speechEndTimeout="auto"
          executionTimeout="15">
    <Speak>Enter your four digit PIN, or say your account name.</Speak>
  </Gather>
  <!-- runs only if Gather fell through -->
  <Speak>We did not get that. Goodbye.</Speak>
  <Hangup/>
</Response>`,
  redirect_true: `<!-- redirect="true" (the default): the XML you
     return from the action URL drives the call. -->
<Response>
  <Speak>Thank you. One moment.</Speak>
  <Redirect>https://you.example/menu</Redirect>
</Response>`,
  redirect_false: `<!-- redirect="false": Vobiz still POSTs the
     action URL, ignores what you return, and runs the
     elements that followed <Gather>. -->
<Speak>We did not get that. Goodbye.</Speak>
<Hangup/>`,
  none: null
};

export const GV_HOOK = {
  num: {
    url: "POST /gather",
    body: {
      CallUUID: GV_CALL,
      From: "+14155550111",
      To: "+14155550100",
      InputType: "dtmf",
      Digits: "4821",
      Speech: ""
    }
  },
  finish: {
    url: "POST /gather",
    body: {
      CallUUID: GV_CALL,
      From: "+14155550111",
      To: "+14155550100",
      InputType: "dtmf",
      Digits: "482",
      Speech: ""
    }
  },
  gap: {
    url: "POST /gather",
    body: {
      CallUUID: GV_CALL,
      From: "+14155550111",
      To: "+14155550100",
      InputType: "dtmf",
      Digits: "48",
      Speech: ""
    }
  },
  exec: {
    url: "POST /gather",
    body: {
      CallUUID: GV_CALL,
      From: "+14155550111",
      To: "+14155550100",
      InputType: "",
      Digits: "",
      Speech: ""
    }
  },
  speech: {
    url: "POST /gather",
    body: {
      CallUUID: GV_CALL,
      From: "+14155550111",
      To: "+14155550100",
      InputType: "speech",
      Digits: "",
      Speech: "my account is northwind",
      SpeechConfidenceScore: "0.92",
      BilledAmount: "0.0050"
    }
  },
  interim: {
    url: "POST /interim",
    body: {
      StableSpeech: "my account is",
      UnstableSpeech: " northwind",
      Stability: "0.65",
      SequenceNumber: "3"
    }
  },
  none: null
};

export const GV_NODES = {
  "1": {
    type: "prompt",
    title: "The prompt plays",
    tag: "Speak",
    screen: "Enter your four digit PIN, or say your account name.",
    desc: "Nested **Speak** and **Play** elements run first. **executionTimeout has not started yet** - the clock only begins once the prompt finishes, which is the single most misread part of Gather.",
    xml: "gather",
    hook: "none",
    to: "2"
  },
  "2": {
    type: "collect",
    title: "Waiting for input",
    tag: "Gather",
    screen: "",
    desc: "The window is open and **executionTimeout** is now running. Press a digit on the pad, or take one of the branches to see what happens when nobody does.",
    xml: "gather",
    hook: "none",
    live: true,
    branches: [{
      label: "🎤 The caller speaks instead",
      to: "s1",
      cls: "ok"
    }, {
      label: "⏱ Nobody presses anything → executionTimeout",
      to: "t_exec",
      cls: "bad"
    }]
  },
  "3": {
    type: "collect",
    title: "Digits are accumulating",
    tag: "Gather",
    screen: "",
    desc: "Every press appends to **Digits** and resets **digitEndTimeout** - that timer measures the gap *between* presses, not the total. The overall window keeps draining underneath it.",
    xml: "gather",
    hook: "none",
    live: true,
    branches: [{
      label: "⏱ Caller pauses too long → digitEndTimeout",
      to: "t_gap",
      cls: "bad"
    }, {
      label: "⏱ Whole window expires → executionTimeout",
      to: "t_exec",
      cls: "bad"
    }]
  },
  "s1": {
    type: "speech",
    title: "Speech is being recognised",
    tag: "interim",
    screen: "“my account is northwind”",
    desc: "With **inputType** including speech, whichever modality arrives first wins and the other is abandoned. While the caller talks, partial transcripts stream to **interimSpeechResultsCallback** with a rising Stability.",
    xml: "none",
    hook: "interim",
    branches: [{
      label: "🔇 The caller stops talking → speechEndTimeout",
      to: "t_speech",
      cls: "ok"
    }]
  },
  "t_num": {
    type: "win",
    title: "numDigits filled",
    tag: "terminator",
    screen: "4821",
    desc: "The 4th digit landed and Vobiz submitted **immediately** - neither timer got a vote. For single-key menus, numDigits=\"1\" gives the snappiest response.",
    xml: "none",
    hook: "num",
    to: "act"
  },
  "t_finish": {
    type: "win",
    title: "finishOnKey pressed",
    tag: "terminator",
    screen: "482 #",
    desc: "The caller signalled they were done. The terminating key **is not included in Digits** - here they typed 482 then #, and you receive 482.",
    xml: "none",
    hook: "finish",
    to: "act"
  },
  "t_gap": {
    type: "warn",
    title: "digitEndTimeout elapsed",
    tag: "terminator",
    screen: "48",
    desc: "No new digit arrived within the gap window, so Vobiz submitted whatever had been collected so far - a **partial** entry. Validate length server-side; do not assume you got all of it.",
    xml: "none",
    hook: "gap",
    to: "act"
  },
  "t_exec": {
    type: "bad",
    title: "executionTimeout elapsed",
    tag: "terminator",
    screen: "",
    desc: "The whole window closed. Vobiz **still POSTs the action URL**, with empty Digits and Speech, and then moves to the next element. This is the case most flows ship broken - check for empty values.",
    xml: "none",
    hook: "exec",
    to: "act"
  },
  "t_speech": {
    type: "win",
    title: "speechEndTimeout elapsed",
    tag: "terminator",
    screen: "“my account is northwind”",
    desc: "Silence held long enough, so recognition stopped and the final transcript went out with a **SpeechConfidenceScore**. Threshold that score before acting on it - and note speech input is billed.",
    xml: "none",
    hook: "speech",
    to: "act"
  },
  "act": {
    type: "decision",
    title: "The action URL is called",
    tag: "action",
    screen: "",
    desc: "One request, whatever ended the Gather. Read **InputType** to see which modality won, then branch on Digits or Speech. What happens next depends on **redirect**.",
    xml: "none",
    hook: "num",
    branches: [{
      label: "redirect=\"true\" → your XML drives the call",
      to: "r_true"
    }, {
      label: "redirect=\"false\" → elements after Gather run",
      to: "r_false"
    }]
  },
  "r_true": {
    type: "xml",
    title: "Your XML takes over",
    tag: "Response",
    screen: "",
    desc: "The document you return replaces the rest of the flow. This is how an IVR menu moves to the next level.",
    xml: "redirect_true",
    hook: "none",
    terminal: true
  },
  "r_false": {
    type: "xml",
    title: "Vobiz runs what followed Gather",
    tag: "Response",
    screen: "",
    desc: "The request was still sent - your response is simply ignored. The elements after **Gather** run blind, unable to tell a successful entry from a timeout.",
    xml: "redirect_false",
    hook: "none",
    terminal: true
  }
};

export const GV_EX = {
  "1": {
    type: "greeting",
    title: "Greeting & language",
    tag: "Gather",
    xml: "lang",
    screen: "Thank you for calling Meridian Telecom. For English press 1. हिन्दी के लिए 2 दबाएं.",
    keys: [{
      k: "1",
      label: "English",
      to: "2",
      act: "en"
    }, {
      k: "2",
      label: "हिन्दी",
      to: "2",
      act: "hi"
    }],
    timeout: {
      to: "end_noinput"
    }
  },
  "2": {
    type: "auth",
    title: "Enter customer ID",
    tag: "Gather",
    xml: "id",
    screen: "Please enter your six digit customer ID, then press hash.",
    input: "id",
    to: "2.1"
  },
  "3": {
    type: "menu",
    title: "Main menu",
    tag: "Gather",
    xml: "menu",
    screen: "Thanks A. Rao. Main menu. Press 1 for billing and payments. Press 2 for technical support. Press 3 for account changes. Press 9 for an advisor at any time. Press 0 to repeat.",
    keys: [{
      k: "1",
      label: "Billing",
      to: "4"
    }, {
      k: "2",
      label: "Technical",
      to: "5"
    }, {
      k: "3",
      label: "Account",
      to: "6"
    }, {
      k: "9",
      label: "Advisor",
      to: "7"
    }, {
      k: "0",
      label: "Repeat",
      to: "3",
      sec: true
    }],
    timeout: {
      to: "end_noinput"
    }
  },
  "4": {
    type: "menu",
    title: "Billing menu",
    tag: "Gather",
    xml: "menu",
    screen: "Billing. Press 1 to hear your balance. Press 2 to make a payment. Press 3 to dispute a charge. Press 0 for the main menu.",
    keys: [{
      k: "1",
      label: "Balance",
      to: "4.1"
    }, {
      k: "2",
      label: "Pay",
      to: "4.2"
    }, {
      k: "3",
      label: "Dispute",
      to: "4.3"
    }, {
      k: "9",
      label: "Advisor",
      to: "7"
    }, {
      k: "0",
      label: "Main menu",
      to: "3",
      sec: true
    }]
  },
  "5": {
    type: "speech",
    title: "Describe the fault",
    tag: "Gather",
    xml: "speech",
    screen: "In a few words, tell me what is not working. For example, say no internet, slow speed, or cannot make calls.",
    to: "5.1"
  },
  "6": {
    type: "menu",
    title: "Account changes",
    tag: "Gather",
    xml: "menu",
    screen: "Account changes. Press 1 to update your mobile number. Press 2 to close your account. Press 0 for the main menu.",
    keys: [{
      k: "1",
      label: "Update mobile",
      to: "6.1"
    }, {
      k: "2",
      label: "Close account",
      to: "6.2"
    }, {
      k: "0",
      label: "Main menu",
      to: "3",
      sec: true
    }]
  },
  "7": {
    type: "auto",
    title: "Advisor hours check",
    tag: "your server",
    xml: "server",
    screen: "(Your server) Checking advisor hours - 9 AM to 8 PM, Monday to Saturday, in IST. Every path that asked for a human converges here.",
    branches: [{
      label: "🕘 Open → check the queue",
      to: "7.1"
    }, {
      label: "🌙 Closed → take a message",
      to: "8"
    }]
  },
  "8": {
    type: "action",
    title: "Voicemail",
    tag: "Record",
    xml: "record",
    screen: "Our advisors have finished for the day. Leave a message after the tone and press hash. We will call you back tomorrow.",
    to: "end_vm"
  },
  "9": {
    type: "menu",
    title: "Post-call survey",
    tag: "Gather",
    xml: "menu",
    screen: "Before you go — how did we do? Press 1 for poor, up to 5 for excellent.",
    keys: [{
      k: "1",
      label: "1 poor",
      to: "end_survey"
    }, {
      k: "2",
      label: "2",
      to: "end_survey"
    }, {
      k: "3",
      label: "3",
      to: "end_survey"
    }, {
      k: "4",
      label: "4",
      to: "end_survey"
    }, {
      k: "5",
      label: "5 great",
      to: "end_survey"
    }]
  },
  "2.1": {
    type: "auto",
    title: "Look the ID up",
    tag: "your server",
    xml: "server",
    screen: "(Your server) Looking the ID up against the CRM. The digits arrive on the action URL without the hash - finishOnKey is never part of Digits.",
    branches: [{
      label: "✔ ID matches an account",
      to: "3",
      cls: "ok",
      act: "authed"
    }, {
      label: "✗ No match — count the attempt",
      to: "2.2",
      cls: "bad",
      act: "try"
    }]
  },
  "2.2": {
    type: "auto",
    title: "Retry or stop?",
    tag: "your server",
    xml: "server",
    screen: "(Your server) The ID did not match. Your application counts the attempt and decides: prompt again, or stop asking. Vobiz has no retry counter of its own - this loop is yours.",
    branches: [{
      label: "↩ Attempts left → ask again",
      to: "2",
      cls: "",
      sec: true
    }, {
      label: "✗ Third failure → stop asking",
      to: "2.3",
      cls: "bad"
    }]
  },
  "2.3": {
    type: "menu",
    title: "Could not identify",
    tag: "Gather",
    xml: "menu",
    screen: "We could not identify you. Press 1 to speak to an advisor, or press 0 to start again.",
    keys: [{
      k: "1",
      label: "Advisor",
      to: "7"
    }, {
      k: "0",
      label: "Start again",
      to: "1",
      sec: true
    }]
  },
  "4.1": {
    type: "auto",
    title: "Read the balance",
    tag: "your server",
    xml: "server",
    screen: "(Your server) Reading the live balance. The branch you take here is your code, not Vobiz.",
    branches: [{
      label: "₹0 outstanding",
      to: "end_nodues",
      cls: "ok"
    }, {
      label: "₹4,820 outstanding",
      to: "4.1.1"
    }]
  },
  "4.1.1": {
    type: "menu",
    title: "Balance & due date",
    tag: "Gather",
    xml: "menu",
    screen: "Your balance is 4,820 rupees, due in four days. Press 1 to pay now. Press 2 to hear that again. Press 0 for the main menu.",
    keys: [{
      k: "1",
      label: "Pay now",
      to: "4.2"
    }, {
      k: "2",
      label: "Repeat",
      to: "4.1.1",
      sec: true
    }, {
      k: "0",
      label: "Main menu",
      to: "3",
      sec: true
    }]
  },
  "4.2": {
    type: "menu",
    title: "Payment options",
    tag: "Gather",
    xml: "menu",
    screen: "Payment. Press 1 to pay the full 4,820 rupees. Press 2 to enter a part amount. Press 0 to go back.",
    keys: [{
      k: "1",
      label: "Pay in full",
      to: "4.2.1"
    }, {
      k: "2",
      label: "Part amount",
      to: "4.2.2"
    }, {
      k: "0",
      label: "Back to billing",
      to: "4",
      sec: true
    }]
  },
  "4.2.1": {
    type: "menu",
    title: "Confirm full payment",
    tag: "Gather",
    xml: "menu",
    screen: "You are about to pay 4,820 rupees. Press 1 to confirm, or 2 to change the amount.",
    keys: [{
      k: "1",
      label: "Confirm",
      to: "4.2.3"
    }, {
      k: "2",
      label: "Change amount",
      to: "4.2",
      sec: true
    }]
  },
  "4.2.2": {
    type: "entry",
    title: "Enter part amount",
    tag: "Gather",
    xml: "amount",
    screen: "Enter the amount in rupees, then press hash.",
    input: "amount",
    to: "4.2.3"
  },
  "4.2.3": {
    type: "auto",
    title: "Charge the card",
    tag: "your server",
    xml: "server",
    screen: "(Your server) Charging the saved card through the payment gateway. This is the one node where a failure is genuinely out of your hands.",
    branches: [{
      label: "✔ Gateway approved",
      to: "4.2.5",
      cls: "ok",
      act: "paid"
    }, {
      label: "✗ Declined by the bank",
      to: "4.2.4",
      cls: "bad"
    }]
  },
  "4.2.5": {
    type: "menu",
    title: "Payment confirmed",
    tag: "Gather",
    xml: "menu",
    screen: "Payment received, 4,820 rupees. A receipt has been sent by SMS. Thank you for calling Meridian.",
    keys: [{
      k: "1",
      label: "Rate the call",
      to: "9"
    }, {
      k: "0",
      label: "Main menu",
      to: "3",
      sec: true
    }]
  },
  "4.2.4": {
    type: "menu",
    title: "Payment declined",
    tag: "Gather",
    xml: "menu",
    screen: "The payment was declined by your bank. Press 1 to try a different amount. Press 9 for an advisor. Press 0 for the main menu.",
    keys: [{
      k: "1",
      label: "Try again",
      to: "4.2",
      sec: true
    }, {
      k: "9",
      label: "Advisor",
      to: "7"
    }, {
      k: "0",
      label: "Main menu",
      to: "3",
      sec: true
    }]
  },
  "4.3": {
    type: "menu",
    title: "Charge dispute",
    tag: "Gather",
    xml: "menu",
    screen: "Charge dispute. Press 1 to raise a ticket now. Press 9 to explain it to an advisor. Press 0 for the main menu.",
    keys: [{
      k: "1",
      label: "Raise ticket",
      to: "end_ticket"
    }, {
      k: "9",
      label: "Advisor",
      to: "7"
    }, {
      k: "0",
      label: "Main menu",
      to: "3",
      sec: true
    }]
  },
  "5.1": {
    type: "auto",
    title: "Match the transcript",
    tag: "your server",
    xml: "server",
    screen: "(Your server) Matching the transcript against known faults. Speech and SpeechConfidenceScore both arrive on the action URL - threshold the score instead of trusting the text.",
    branches: [{
      label: "✔ Known fault, confidence 0.91",
      to: "5.2",
      cls: "ok"
    }, {
      label: "✗ Confidence 0.42 → ask again",
      to: "5",
      cls: "",
      sec: true
    }, {
      label: "✗ Nothing said → advisor",
      to: "7",
      cls: "bad"
    }]
  },
  "5.2": {
    type: "menu",
    title: "Known fault",
    tag: "Gather",
    xml: "menu",
    screen: "That is a known fault in your area. Press 1 to get the fix steps by SMS. Press 2 if you have already tried that. Press 0 for the main menu.",
    keys: [{
      k: "1",
      label: "SMS the steps",
      to: "end_sms"
    }, {
      k: "2",
      label: "Already tried",
      to: "5.3"
    }, {
      k: "0",
      label: "Main menu",
      to: "3",
      sec: true
    }]
  },
  "5.3": {
    type: "auto",
    title: "Run a line test",
    tag: "your server",
    xml: "server",
    screen: "(Your server) Running a line test on the account. Nothing is spoken to the caller while this happens - keep it under a second or play a Wait.",
    branches: [{
      label: "✔ Line fault found → engineer",
      to: "end_engineer",
      cls: "ok"
    }, {
      label: "✗ Line is clean → advisor",
      to: "7"
    }]
  },
  "6.1": {
    type: "entry",
    title: "New mobile number",
    tag: "Gather",
    xml: "id",
    screen: "Enter the new ten digit mobile number, then press hash.",
    input: "mobile",
    to: "6.1.1"
  },
  "6.1.1": {
    type: "entry",
    title: "Enter the SMS code",
    tag: "Gather",
    xml: "id",
    screen: "We sent a code to +9198•••••21. Enter the four digit code, then press hash.",
    input: "otp",
    to: "6.1.2"
  },
  "6.1.2": {
    type: "auto",
    title: "Verify the code",
    tag: "your server",
    xml: "server",
    screen: "(Your server) Verifying the code. A wrong code loops back to the number entry - another retry loop you own.",
    branches: [{
      label: "✔ Code correct",
      to: "end_mobile",
      cls: "ok"
    }, {
      label: "✗ Wrong code → re-enter the number",
      to: "6.1",
      cls: "bad",
      sec: true
    }]
  },
  "6.2": {
    type: "menu",
    title: "Close the account",
    tag: "Gather",
    xml: "menu",
    screen: "Closing an account has to be done with an advisor. Press 1 to be connected, or 0 to return to the main menu.",
    keys: [{
      k: "1",
      label: "Speak to advisor",
      to: "7"
    }, {
      k: "0",
      label: "Main menu",
      to: "3",
      sec: true
    }]
  },
  "7.1": {
    type: "auto",
    title: "Queue depth",
    tag: "your server",
    xml: "server",
    screen: "(Your server) Reading the live queue depth from your ACD. Position 11 today.",
    branches: [{
      label: "Short queue → connect now",
      to: "7.2",
      cls: "ok"
    }, {
      label: "11 ahead → offer a callback",
      to: "7.3"
    }]
  },
  "7.2": {
    type: "action",
    title: "Dial the advisor group",
    tag: "Dial",
    xml: "dial",
    screen: "Connecting you now. Dial rings the advisor group; the first phone to answer is bridged and the others are dropped with LOSE_RACE.",
    terminal: true
  },
  "7.3": {
    type: "menu",
    title: "Callback or hold",
    tag: "Gather",
    xml: "menu",
    screen: "There are 11 callers ahead of you, about twelve minutes. Press 1 for a callback when it is your turn. Press 2 to hold anyway. Press 0 for the main menu.",
    keys: [{
      k: "1",
      label: "Callback",
      to: "end_cb"
    }, {
      k: "2",
      label: "Hold anyway",
      to: "7.2"
    }, {
      k: "0",
      label: "Main menu",
      to: "3",
      sec: true
    }]
  },
  "end_nodues": {
    type: "end",
    title: "END · Nothing due",
    tag: "Hangup",
    xml: "end",
    screen: "Your account is fully paid, nothing is due. Thank you for calling Meridian.",
    terminal: true
  },
  "end_ticket": {
    type: "end",
    title: "END · Dispute raised",
    tag: "Hangup",
    xml: "end",
    screen: "Dispute raised, ticket 51204. An advisor will review it within two working days. Thank you.",
    terminal: true
  },
  "end_sms": {
    type: "end",
    title: "END · Steps sent",
    tag: "Hangup",
    xml: "end",
    screen: "The fix steps are on their way by SMS. Thank you for calling Meridian.",
    terminal: true
  },
  "end_engineer": {
    type: "end",
    title: "END · Engineer booked",
    tag: "Hangup",
    xml: "end",
    screen: "A line fault is confirmed and an engineer is booked for tomorrow morning. Ticket 51204. Thank you.",
    terminal: true
  },
  "end_mobile": {
    type: "end",
    title: "END · Mobile updated",
    tag: "Hangup",
    xml: "end",
    screen: "Your mobile number has been updated. Thank you for calling Meridian.",
    terminal: true
  },
  "end_cb": {
    type: "end",
    title: "END · Callback booked",
    tag: "Hangup",
    xml: "end",
    screen: "A callback is booked. We will ring you on your registered number. Thank you.",
    terminal: true
  },
  "end_vm": {
    type: "end",
    title: "END · Message saved",
    tag: "Hangup",
    xml: "end",
    screen: "Your message is saved, reference 51204. Thank you for calling Meridian.",
    terminal: true
  },
  "end_survey": {
    type: "end",
    title: "END · Survey done",
    tag: "Hangup",
    xml: "end",
    screen: "Thank you for the feedback. Goodbye.",
    terminal: true
  },
  "end_noinput": {
    type: "end",
    title: "END · No input",
    tag: "Hangup",
    xml: "end",
    screen: "We did not receive any input. Goodbye.",
    terminal: true
  }
};

export const GV_EX_XML = {
  lang: `<Gather action="https://tel.example/lang" inputType="dtmf"
        numDigits="1" executionTimeout="8">
  <Speak>For English press 1. Hindi ke liye 2 dabayein.</Speak>
</Gather>
<Redirect>https://tel.example/no-input</Redirect>`,
  id: `<Gather action="https://tel.example/identify" inputType="dtmf"
        numDigits="6" finishOnKey="#"
        digitEndTimeout="4" executionTimeout="20">
  <Speak>Enter your six digit customer ID, then hash.</Speak>
</Gather>`,
  menu: `<Gather action="https://tel.example/menu" inputType="dtmf"
        numDigits="1" executionTimeout="10">
  <Speak>Press 1 for billing, 2 for support, 3 for account…</Speak>
</Gather>
<Redirect>https://tel.example/no-input</Redirect>`,
  speech: `<Gather action="https://tel.example/fault" inputType="speech"
        language="en-IN" speechModel="phone_call"
        speechEndTimeout="auto"
        hints="no internet, slow speed, cannot make calls">
  <Speak>Tell me what is not working.</Speak>
</Gather>`,
  amount: `<Gather action="https://tel.example/amount" inputType="dtmf"
        numDigits="6" finishOnKey="#" executionTimeout="25">
  <Speak>Enter the amount in rupees, then hash.</Speak>
</Gather>`,
  server: `<!-- No XML runs here. Your action URL received the input,
     made the decision, and returns the next document.
     Retry counters, queue depth and business hours all
     live in your code - Vobiz has none of them. -->`,
  dial: `<Dial callerId="+912240000000" timeout="25" timeLimit="3600"
      dialMusic="https://tel.example/queue-music"
      callbackUrl="https://tel.example/dial-events"
      action="https://tel.example/dial-result">
  <Number>+912249000001</Number>
  <Number>+912249000002</Number>
  <User>sip:advisor7@tel.example</User>
</Dial>`,
  record: `<Record action="https://tel.example/voicemail"
        maxLength="180" finishOnKey="#"
        playBeep="true" fileFormat="mp3"
        recordSession="false"/>`,
  end: `<Speak>Thank you for calling Meridian.</Speak>
<Hangup/>`
};

export const gvLayout = N => {
  const primary = id => {
    const n = N[id], out = [];
    if (n.keys) n.keys.forEach(k => {
      if (!k.sec && k.to !== id) out.push(k.to);
    });
    if (n.branches) n.branches.forEach(b => {
      if (!b.sec && b.to !== id) out.push(b.to);
    });
    if (n.to) out.push(n.to);
    if (n.live) ["3", "t_num", "t_finish"].forEach(t => {
      if (t !== id && N[t]) out.push(t);
    });
    return out;
  };
  const rank = {
    "1": 0
  };
  const count = Object.keys(N).length;
  for (let pass = 0; pass < count; pass++) {
    let changed = false;
    for (const id in N) {
      const r = rank[id];
      if (r === undefined) continue;
      primary(id).forEach(t => {
        if (N[t] && (rank[t] === undefined || rank[t] < r + 1)) {
          rank[t] = r + 1;
          changed = true;
        }
      });
    }
    if (!changed) break;
  }
  for (const id in N) if (rank[id] === undefined) rank[id] = 1;
  const COLW = 248, ROWH = 84, PADX = 40, PADY = 28, NW = 194, NH = 52;
  const byRank = {};
  for (const id in N) (byRank[rank[id]] = byRank[rank[id]] || []).push(id);
  const pos = {};
  Object.keys(byRank).map(Number).sort((a, b) => a - b).forEach(r => {
    byRank[r].forEach((id, i) => {
      pos[id] = {
        x: PADX + r * COLW,
        y: PADY + i * ROWH
      };
    });
  });
  const edges = [];
  const add = (from, to, sec) => {
    const a = pos[from], b = pos[to];
    if (!a || !b) return;
    const back = b.x <= a.x;
    const x1 = a.x + NW, y1 = a.y + NH / 2;
    const x2 = back ? b.x + NW : b.x, y2 = b.y + NH / 2;
    const mx = (x1 + x2) / 2;
    edges.push({
      key: from + "->" + to + (sec ? "s" : ""),
      sec: Boolean(sec),
      d: back ? `M${x1},${y1} C${x1 + 60},${y1 - 42} ${x2 + 60},${y2 - 42} ${x2},${y2}` : `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`
    });
  };
  for (const id in N) {
    const n = N[id];
    if (n.keys) n.keys.forEach(k => add(id, k.to, k.sec));
    if (n.branches) n.branches.forEach(b => add(id, b.to, b.sec));
    if (n.to) add(id, n.to, false);
    if (n.timeout) add(id, n.timeout.to, true);
    if (n.live) ["3", "t_num", "t_finish"].forEach(t => {
      if (t !== id && N[t]) add(id, t, false);
    });
  }
  let w = 0, h = 0;
  for (const id in pos) {
    w = Math.max(w, pos[id].x + NW);
    h = Math.max(h, pos[id].y + NH);
  }
  return {
    pos,
    edges,
    w: w + 36,
    h: h + 36,
    NW,
    NH
  };
};

export const GV_LAYOUT = gvLayout(GV_NODES);
export const GV_EX_LAYOUT = gvLayout(GV_EX);

export const GV_FLOWS = {
  element: {
    label: "The Gather element",
    nodes: GV_NODES,
    layout: GV_LAYOUT,
    xml: GV_XML,
    live: true
  },
  example: {
    label: "Example · a full IVR",
    nodes: GV_EX,
    layout: GV_EX_LAYOUT,
    xml: GV_EX_XML,
    live: false
  }
};

export const GvRich = ({text}) => <span>{String(text).split(/\*\*(.+?)\*\*/g).map((part, i) => i % 2 ? <strong key={i}>{part}</strong> : <span key={i}>{part}</span>)}</span>;

export const GV_DRAG = {
  at: null
};
export const gvCanvasEl = () => document.getElementById("gvCanvas");

export const GvXml = ({text}) => <pre><code>{text.split("\n").map((line, i) => {
  if (line.trim().startsWith("<!--") || line.trim().startsWith("--") || (/-->$/).test(line.trim())) return <div key={i} className="gv-cm">{line}</div>;
  const parts = line.split(/([\w:.-]+="[^"]*"|<\/?[A-Za-z][\w:.-]*|\/>|>)/g).filter(p => p);
  return <div key={i}>{parts.map((p, j) => {
    if ((/^[\w:.-]+="/).test(p)) {
      const eq = p.indexOf("=");
      return <span key={j}><span className="gv-attr">{p.slice(0, eq)}</span>=<span className="gv-val">{p.slice(eq + 1)}</span></span>;
    }
    if ((/^<\/?[A-Za-z]/).test(p) || p === ">" || p === "/>") return <span key={j} className="gv-tag">{p}</span>;
    return <span key={j}>{p}</span>;
  })}</div>;
})}</code></pre>;

export const GvBody = ({body}) => <pre><code>{Object.entries(body).map(([k, v]) => <div key={k}>{"  "}<span className="gv-key">{k}</span>=
      {v === "" ? <span className="gv-empty">(empty)</span> : <span className="gv-str">{v}</span>}
    </div>)}</code></pre>;

export const GatherFlow = () => {
  const NUM_DIGITS = 4;
  const FINISH = "#";
  const [flowId, setFlowId] = React.useState("element");
  const [tries, setTries] = React.useState(0);
  const [authed, setAuthed] = React.useState(false);
  const [paid, setPaid] = React.useState(false);
  const [cur, setCur] = React.useState("1");
  const [digits, setDigits] = React.useState("");
  const [path, setPath] = React.useState(["1"]);
  const [visited, setVisited] = React.useState(() => new Set(["1"]));
  const [view, setView] = React.useState({
    s: 1,
    x: 0,
    y: 0
  });
  const F = GV_FLOWS[flowId];
  const NODES = F.nodes;
  const L = F.layout;
  const n = NODES[cur] || NODES["1"];
  const isExample = flowId === "example";
  const applyAct = act => {
    if (act === "authed") {
      setAuthed(true);
      setTries(0);
    }
    if (act === "try") setTries(t => Math.min(3, t + 1));
    if (act === "paid") setPaid(true);
  };
  const go = (id, fromMap, act) => {
    if (!NODES[id]) return;
    if (act) applyAct(act);
    if (NODES[id].input) setDigits("");
    setCur(id);
    if (fromMap) {
      setPath([id]);
      setVisited(new Set([id]));
      setDigits("");
    } else {
      setPath(p => p.concat(id));
      setVisited(v => new Set(v).add(id));
    }
  };
  const restart = () => {
    setCur("1");
    setDigits("");
    setPath(["1"]);
    setVisited(new Set(["1"]));
    setTries(0);
    setAuthed(false);
    setPaid(false);
  };
  const pickFlow = id => {
    setFlowId(id);
    setCur("1");
    setDigits("");
    setPath(["1"]);
    setVisited(new Set(["1"]));
    setTries(0);
    setAuthed(false);
    setPaid(false);
  };
  const press = k => {
    if (!collecting) return;
    if (k !== FINISH && !(/^[0-9]$/).test(k)) return;
    if (k === FINISH) {
      if (isExample && n.input) {
        go(n.to);
        return;
      }
      setDigits(d => d);
      go("t_finish");
      return;
    }
    const next = digits + k;
    setDigits(next);
    if (isExample && n.input) return;
    if (next.length >= NUM_DIGITS) {
      go("t_num");
      return;
    }
    if (cur !== "3") go("3");
  };
  const fit = () => {
    const el = gvCanvasEl();
    if (!el) return;
    const r = el.getBoundingClientRect();
    const s = Math.min((r.width - 28) / L.w, (r.height - 28) / L.h, 1.05);
    setView({
      s: Math.max(0.2, s),
      x: 14,
      y: 14
    });
  };
  React.useEffect(() => {
    fit();
  }, []);
  React.useEffect(() => {
    const el = gvCanvasEl();
    if (!el) return undefined;
    const onWheel = e => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const r = el.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
      setView(v => {
        const f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
        const ns = Math.min(2.2, Math.max(0.2, v.s * f));
        return {
          s: ns,
          x: mx - (mx - v.x) * (ns / v.s),
          y: my - (my - v.y) * (ns / v.s)
        };
      });
    };
    el.addEventListener("wheel", onWheel, {
      passive: false
    });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);
  React.useEffect(() => {
    const onKey = e => {
      if (!collecting) return;
      if ((/^[0-9#]$/).test(e.key)) {
        e.preventDefault();
        press(e.key);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  const onDown = e => {
    if (e.target.closest && e.target.closest(".gv-node")) return;
    GV_DRAG.at = {
      x: e.clientX - view.x,
      y: e.clientY - view.y
    };
  };
  const onMove = e => {
    if (!GV_DRAG.at) return;
    const d = GV_DRAG.at;
    setView(v => ({
      ...v,
      x: e.clientX - d.x,
      y: e.clientY - d.y
    }));
  };
  const onUp = () => {
    GV_DRAG.at = null;
  };
  const zoom = f => setView(v => ({
    ...v,
    s: Math.min(2.2, Math.max(0.2, v.s * f))
  }));
  const collecting = Boolean(n.live) || Boolean(isExample && n.input);
  const usable = k => collecting && (k === FINISH || (/^[0-9]$/).test(k));
  const typed = ["t_num", "t_finish", "t_gap"].indexOf(cur) >= 0 && digits ? digits : null;
  const xml = n.xml ? F.xml[n.xml] : null;
  const baseHook = isExample ? null : GV_HOOK[n.hook];
  const hook = baseHook && typed ? {
    url: baseHook.url,
    body: {
      ...baseHook.body,
      Digits: typed
    }
  } : baseHook;
  const screen = collecting && digits ? digits : n.live ? "waiting for input" : typed || n.screen || "—";
  const isDigits = (/^[0-9 #*]+$/).test(screen);
  return <div className="gather-visualizer not-prose">
      <main className="gv-shell">
        <div className="gv-intro">
          <p className="gv-eyebrow">Interactive input flow</p>
          <h1>{isExample ? "A real IVR, node by node." : "Gather is a race. Walk it and see which condition wins."}</h1>
          <p className="gv-lede">
            {isExample ? "The same walkthrough over a whole customer line: identification with a retry counter, three levels of menu, a speech gate, a queue and a survey. Every violet node is your server deciding - Vobiz has no retry counter, no queue depth and no business hours of its own." : "Four things can end a Gather: the digit count fills, the finish key is pressed, the gap between digits runs out, or the whole window expires. Use the dial pad on the left, or take a branch to see a timeout fire."}
          </p>
          <div className="gv-flowpick">
            {Object.keys(GV_FLOWS).map(id => <button type="button" key={id} onClick={() => pickFlow(id)} className={flowId === id ? "is-on" : ""}>
                {GV_FLOWS[id].label}
                <span>{Object.keys(GV_FLOWS[id].nodes).length} nodes</span>
              </button>)}
          </div>
        </div>

        <div className="gv-grid">
          <aside className="gv-rail">
            {isExample ? <div className="gv-state">
                <div className={"gv-cell" + (authed ? " is-ok" : " is-warn")}>
                  <span>identified</span><b>{authed ? "yes · A. Rao" : "no"}</b>
                </div>
                <div className={"gv-cell" + (tries === 0 ? "" : tries >= 3 ? " is-bad" : " is-warn")}>
                  <span>id attempts</span><b>{tries} of 3</b>
                </div>
                <div className={"gv-cell" + (paid ? " is-ok" : " is-warn")}>
                  <span>balance due</span><b>{paid ? "₹0 · paid" : "₹4,820"}</b>
                </div>
                <div className="gv-cell">
                  <span>queue ahead</span><b>11</b>
                </div>
              </div> : null}
            <div className="gv-phone">
              <div className="gv-screen">
                <div className="gv-nid">NODE {cur.toUpperCase()}</div>
                <div className="gv-ntitle">{n.title}</div>
                <div className={"gv-readout" + (isDigits ? " is-digits" : " is-prose")}>{screen}</div>
                {n.desc ? <p className="gv-desc"><GvRich text={n.desc} /></p> : null}
              </div>

              <div className="gv-pad">
                {["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"].map(d => {
    const hit = isExample && n.keys ? n.keys.find(k => k.k === d) : null;
    const live = hit ? true : usable(d);
    const label = hit ? hit.label : !live ? "" : d === FINISH ? "submit" : "collect";
    return <button type="button" key={d} disabled={!live} onClick={() => hit ? go(hit.to, false, hit.act) : press(d)} className={"gv-key" + (live ? " is-live" : " is-dead") + (!hit && d === FINISH ? " is-fk" : "")}>
                      <span className="gv-d">{d}</span>
                      <span className="gv-kl">{label}</span>
                    </button>;
  })}
              </div>
              <div className="gv-padnote">
                {n.keys && isExample ? "press a lit key to take that option" : collecting ? `0-9 collect · ${FINISH} submits · ${digits.length}${n.live ? " of " + NUM_DIGITS : ""} entered` : "the pad is idle at this step"}
              </div>

              {n.branches ? <div className="gv-branches">
                  {n.branches.map(b => <button type="button" key={b.to + b.label} className={"gv-branch" + (b.cls ? " is-" + b.cls : "")} onClick={() => go(b.to, false, b.act)}>
                      {b.label === "RETRYLABEL" ? b.label : b.label}
                    </button>)}
                </div> : n.to && !n.terminal && !(isExample && (n.input || n.type === "speech")) ? <div className="gv-branches">
                  <button type="button" className="gv-branch is-ok" onClick={() => go(n.to)}>→ Continue</button>
                </div> : null}

              {n.timeout ? <div className="gv-branches">
                  <button type="button" className="gv-branch is-bad" onClick={() => go(n.timeout.to)}>
                    ⏱ Caller presses nothing → executionTimeout
                  </button>
                </div> : null}

              {isExample && n.type === "speech" ? <div className="gv-branches">
                  {["“There is no internet since morning”", "“Umm… it is not working properly”", "(says nothing)"].map(l => <button type="button" key={l} className="gv-branch" onClick={() => go(n.to)}>🎤 {l}</button>)}
                </div> : null}

              {n.terminal ? <div className={"gv-endbar" + (n.type === "action" ? " is-act" : "")}>
                  {n.type === "action" ? "Bridged to an advisor" : "Call ended"}
                </div> : null}
            </div>

            <div className="gv-card">
              <h3>XML that runs here<span className={"gv-el " + (xml ? "is-on" : "is-off")}>{xml ? "your document" : "none"}</span></h3>
              {xml ? <GvXml text={xml} /> : <p className="gv-none">No XML executes here - Vobiz is collecting input or deciding what ended it.</p>}
            </div>

            <div className="gv-card">
              <h3>Webhook fired here<span className={"gv-el " + (hook ? "is-on" : "is-off")}>{hook ? hook.url : "none"}</span></h3>
              {hook ? <GvBody body={hook.body} /> : <p className="gv-none">Nothing is sent to your server at this step.</p>}
            </div>

            <div className="gv-log">
              <h3>Path taken</h3>
              <div className="gv-crumbs">
                {path.map((id, i) => <span className="gv-crumb" key={id + i}><b>{id.toUpperCase()}</b> {NODES[id].title}</span>)}
              </div>
            </div>
          </aside>

          <div className="gv-canvaswrap">
            <div className="gv-hint">⌘/Ctrl + scroll = zoom · drag = pan · click a node to jump</div>
          <div className="gv-canvas" id="gvCanvas" onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
            <div className="gv-viewport" style={{
    transform: `translate(${view.x}px,${view.y}px) scale(${view.s})`
  }}>
              <svg className="gv-edges" width={L.w} height={L.h}>
                {L.edges.map(e => <path key={e.key} d={e.d} fill="none" stroke={e.sec ? "var(--gv-faint)" : "rgba(232,60,0,.42)"} strokeWidth={e.sec ? 1.2 : 1.7} strokeDasharray={e.sec ? "4 3" : undefined} />)}
              </svg>
              {Object.keys(NODES).map(id => {
    const nd = NODES[id], p = L.pos[id];
    return <button type="button" key={id} onClick={() => go(id, true)} className={"gv-node is-" + nd.type + (id === cur ? " is-active" : "") + (visited.has(id) && id !== cur ? " is-visited" : "")} style={{
      left: p.x,
      top: p.y
    }}>
                    <span className="gv-nid2">{id.toUpperCase()}<span className="gv-ntag">{nd.tag}</span></span>
                    <span className="gv-nt">{nd.title}</span>
                  </button>;
  })}
            </div>
            <div className="gv-zoom">
              <button type="button" onClick={() => zoom(1.18)}>+</button>
              <button type="button" onClick={() => zoom(1 / 1.18)}>−</button>
              <button type="button" onClick={fit}>Fit</button>
              <button type="button" onClick={restart}>↻ Restart</button>
            </div>
            <div className="gv-legend">
              <div><i style={{
    background: "var(--gv-ice)"
  }} /> Prompt</div>
              <div><i style={{
    background: "var(--gv-sig)"
  }} /> Collecting</div>
              <div><i style={{
    background: "var(--gv-mint)"
  }} /> Input captured</div>
              <div><i style={{
    background: "var(--gv-amber)"
  }} /> Partial input</div>
              <div><i style={{
    background: "var(--gv-rose)"
  }} /> Nothing captured</div>
            </div>
          </div>
          </div>
        </div>

        <div className="gv-notes">
          <div><strong>numDigits wins early</strong><span>The moment the Nth digit lands, Vobiz submits - before either timer has a say.</span></div>
          <div><strong>finishOnKey is dropped</strong><span>The terminating key submits the input but is never included in <code>Digits</code>.</span></div>
          <div><strong>digitEndTimeout is a gap</strong><span>It measures silence between presses and resets on each one, while the overall window keeps draining.</span></div>
          <div><strong>executionTimeout posts anyway</strong><span>On expiry Vobiz still POSTs with empty values and moves on. Always put fallback XML after Gather.</span></div>
        </div>

        <p className="gv-flag">
          <strong>One thing this page does not claim.</strong> Whether a DTMF press interrupts a still-playing
          prompt is not documented, so here the prompt always plays out before the window opens.
        </p>

        <div className="gv-footer-link">
          <a href="/docs/xml/gather">Read the Gather reference <span aria-hidden="true">→</span></a>
          <a href="/docs/xml/gather/detecting-speech-inputs">Speech input <span aria-hidden="true">→</span></a>
          <a href="/docs/resources/dial-transfer-visualizer">Dial transfer visualizer <span aria-hidden="true">→</span></a>
        </div>
      </main>
    </div>;
};

<GatherFlow />


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.