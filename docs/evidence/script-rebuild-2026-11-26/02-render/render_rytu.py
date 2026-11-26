"""Synthetic Rytu Khata campaign CallScript compiled through the real code (read-only render).
English placeholders stand in for every Telugu line the writer would produce."""
import json
import os
import sys

os.environ.setdefault("ENGINE", "thinnest")

from calevate_shared.call_script import (
    CallScript, ConversationStage, ProcedureStep, StageBranch, StepOutcome, ScenarioQa,
    ScenarioQaText, SpeakingStyle, Objection, ExampleLine, Capabilities, CollectField,
    compile_call_script, native_steps, without_outline, render_steps, without_placed_opening,
)
from calevate_shared.engine import (
    AgentConfig, engine_prompt_layers, compose_engine_prompt, compose_first_utterance,
    DisclosurePosture, notice_fields, call_instructions, sends_our_call_rules,
)

T = "te-IN"
def ph(s):  # placeholder for a Telugu line the writer would write
    return f"<TE: {s}>"

stages = [
    ConversationStage(id="s1", step=1, name="Introduction",
        instruction="Go on from their answer to the opening. Ask whether they registered on the Rytu Khata website.",
        sounds_like=ph("OK-andi, did you register on the Rytu Khata website?"),
        branches=[StageBranch(when="They are busy now", target="call_back"),
                  StageBranch(when="They say they never registered", target="s4"),
                  StageBranch(when="Not interested", target="end")],
        otherwise="s2"),
    ConversationStage(id="s2", step=2, name="App on home screen",
        instruction="Help them put the app on the home screen of their phone.",
        sounds_like=ph("OK-andi, please open the browser on your phone and tell me when it is open."),
        procedure=[ProcedureStep(action="Ask them to open Chrome on their phone", wait_for="they say the browser is open"),
                   ProcedureStep(action="Ask them to type rytukhata.com and open it", wait_for="they see the Rytu Khata page"),
                   ProcedureStep(action="Ask them to tap the install button at the top", wait_for="they see an Install prompt"),
                   ProcedureStep(action="Ask them to tap Install", wait_for="they see the icon on the home screen")],
        branches=[StageBranch(when="They use an iPhone", target="s2"),
                  StageBranch(when="Still stuck after every way", target="call_back")],
        otherwise="s3"),
    ConversationStage(id="s3", step=3, name="Login",
        instruction="Help them log in with their mobile number.",
        sounds_like=ph("Now open the app and enter your mobile number, tell me when you see the OTP screen."),
        procedure=[ProcedureStep(action="Ask them to open the app from the icon", wait_for="the app is open"),
                   ProcedureStep(action="Ask them to enter their mobile number and tap Get OTP", wait_for="they got an OTP"),
                   ProcedureStep(action="Ask them to enter the OTP", wait_for="they are logged in")],
        branches=[StageBranch(when="No OTP arrives", target="call_back")],
        otherwise="s5"),
    ConversationStage(id="s4", step=3, name="Not registered",
        instruction="They have not registered. Help them register on the website first.",
        scripts={T: ph("No problem-andi, let us register first. Please tap Register on the page.")},
        qa=[ScenarioQa(question="Is it free?", answer="Registration is free.",
                       translations={T: ScenarioQaText(question=ph("Is it free?"), answer=ph("Yes-andi, registering is free."))})],
        otherwise="s3"),
    ConversationStage(id="s5", step=4, name="Language",
        instruction="Help them set the app language to Telugu.",
        sounds_like=ph("OK-andi, tap the menu at the top and choose Telugu, tell me when it shows Telugu."),
        procedure=[ProcedureStep(action="Ask them to tap the menu", wait_for="the menu is open"),
                   ProcedureStep(action="Ask them to choose Telugu", wait_for="the screen shows Telugu")],
        otherwise="s6"),
    ConversationStage(id="s6", step=5, name="My Farms",
        instruction="Help them add their first farm in My Farms.",
        sounds_like=ph("Very good-andi! Now tap My Farms and then Add Farm, tell me when the form opens."),
        procedure=[ProcedureStep(action="Ask them to tap My Farms", wait_for="My Farms is open"),
                   ProcedureStep(action="Ask them to tap Add Farm and type the farm name", wait_for="the name is typed"),
                   ProcedureStep(action="Ask them to enter the acres and tap Save", wait_for="the farm is listed")],
        collect=["Number of farms", "Main crop"],
        otherwise="s7"),
    ConversationStage(id="s7", step=6, name="First expense",
        instruction="Help them enter one expense for that farm.",
        sounds_like=ph("Super-andi. Now tap Expenses and Add, and enter one cost, like seeds."),
        procedure=[ProcedureStep(action="Ask them to tap Expenses then Add", wait_for="the expense form is open"),
                   ProcedureStep(action="Ask them to choose the farm, type an amount and tap Save", wait_for="the expense is saved")],
        otherwise="s8"),
    ConversationStage(id="s8", step=7, name="First sale",
        instruction="Help them enter one crop sale.",
        sounds_like=ph("OK-andi, now tap Sales and Add, and enter one sale."),
        procedure=[ProcedureStep(action="Ask them to tap Sales then Add", wait_for="the sale form is open"),
                   ProcedureStep(action="Ask them to enter the crop, the amount and tap Save", wait_for="the sale is saved")],
        otherwise="s9"),
    ConversationStage(id="s9", step=8, name="Dashboard",
        instruction="Ask them to open the Dashboard and say what they see; explain it adds up expenses and sales.",
        sounds_like=ph("Now tap Dashboard-andi; what do you see there?"),
        otherwise="s10"),
    ConversationStage(id="s10", step=9, name="Close", mode="say",
        instruction="Thank them and close.",
        scripts={T: ph("Thank you-andi, any doubt, call us. Have a good day.")},
        otherwise="end"),
]
outcomes = [StepOutcome(step=n, outcome=o) for n, o in [
    (1, "The person says whether they registered on the website"),
    (2, "The person says the Rytu Khata icon is on their home screen"),
    (3, "The person says they are logged in"),
    (4, "The person says the app shows Telugu"),
    (5, "The person says their first farm is listed in My Farms"),
    (6, "The person says one expense is saved"),
    (7, "The person says one sale is saved"),
    (8, "The person says what the dashboard shows"),
    (9, "The person has been thanked"),
]]
script = CallScript(
    schema_version=2,
    business_line="Rytu Khata is a farm accounts app for farmers in Telangana and Andhra Pradesh.",
    identity="You are Varsha from Rytu Khata.",
    goal="Help registered farmers install the Rytu Khata app and enter their first farm, expense and sale.",
    outbound_purpose="to help them start using the Rytu Khata app",
    opening_line=ph("Namaskaram {{lead_name}} garu, calling from Rytu Khata, is now a good time to talk?"),
    style=SpeakingStyle(tone="Warm, patient, slow with steps.", address_form="garu / andi",
                        sample_phrases=[ph("No hurry-andi"), ph("Take your time-andi")]),
    stages=stages,
    step_outcomes=outcomes,
    objections=[Objection(objection="I am busy", response="Ask a day and time that suits them and book a call back."),
                Objection(objection="How did you get my number?", response="They registered on the Rytu Khata website.")],
    ending="Thank them warmly and end the call.",
    example_exchange=[ExampleLine(speaker="caller", text=ph("Hello?")),
                      ExampleLine(speaker="agent", text=ph("OK-andi, did you register on the website?")),
                      ExampleLine(speaker="caller", text=ph("Yes, I registered.")),
                      ExampleLine(speaker="agent", text=ph("Super-andi, please open the browser and tell me when it is open."))],
    example_needs_review=True,
)
collect = (CollectField(label="Number of farms"), CollectField(label="Main crop"),
           CollectField(label="Satisfaction level", reason="for the team"))

body = compile_call_script(script, collect=collect)
can = Capabilities(call_backs=True, hand_over=False)
steps = native_steps(script, can=can)
instr_body = without_placed_opening(without_outline(body))

# Campaign holder: give_callers_time.holder_has_screen = asks_caller_to_act(script)
try:
    from apps.api.agents.give_callers_time import holder_has_screen, holder_gives_time
    screen = holder_has_screen(script, agent_switch=False)
    gives_time = holder_gives_time(None, script)
except Exception as exc:  # noqa: BLE001
    print("holder import failed:", repr(exc), file=sys.stderr)
    screen, gives_time = True, True
try:
    from apps.api.agents.service import platform_filler_lines, platform_nudge_phrase
    fillers = platform_filler_lines((T,))
    nudge = platform_nudge_phrase((T,))
except Exception as exc:  # noqa: BLE001
    print("service import failed:", repr(exc), file=sys.stderr)
    from calevate_shared.spoken_style import thinking_lines
    fillers, nudge = tuple(thinking_lines((T,))[:8]), ""

posture = DisclosurePosture(
    ai_disclosure_line=ph("I am Varsha, an AI assistant from Rytu Khata."), ai_disclosure_enabled=True,
    recording_notice_line=ph("This call is recorded."), recording_notice_enabled=True)

cfg = AgentConfig(
    tenant_id="0199a0b0-0000-7000-8000-000000000001", agent_id="0199a0b0-0000-7000-8000-000000000002",
    name="Varsha · Rytu Khata onboarding", business="Rytu Khata", direction="outbound",
    language_primary=T, system_prompt=instr_body, script_steps=steps,
    facts_in_knowledge=True, knowledge_tool="search_knowledge", callbacks_offered=True,
    engine_own_rules=True, engine_call_instructions=True, caller_has_screen=screen,
    filler_lines=fillers, nudge_phrase=nudge or None, engine_own_voice_key=False,
    engine_workspace="org_test", call_is_recorded=True, holder="campaign:x",
    **notice_fields(posture, call_is_recorded=True),
)

out = {}
layers = engine_prompt_layers(cfg)
out["layers"] = [(name, len(text)) for name, text in layers]
out["instructions_total"] = len(compose_engine_prompt(cfg))
out["compiled_body_chars"] = len(body)
out["instr_body_chars"] = len(instr_body)
out["caller_has_screen"] = screen
out["holder_gives_time"] = gives_time
out["fillers"] = list(fillers)
out["nudge"] = nudge
out["greeting"] = compose_first_utterance(cfg)
out["sends_our_call_rules"] = sends_our_call_rules(cfg)
out["call_instructions"] = call_instructions(cfg) if sends_our_call_rules(cfg) else None
try:
    from apps.api.engine.thinnest import ThinnestEngine
    eng = ThinnestEngine(api_key="ta_live_test")
    wire = eng._agent_body(cfg)
    out["wire"] = wire
except Exception as exc:  # noqa: BLE001
    out["wire_error"] = repr(exc)

base = sys.argv[1]
with open(f"{base}/rytu_instructions.txt", "w", encoding="utf-8") as f:
    for name, text in layers:
        f.write(f"\n########## LAYER {name} ({len(text)} chars) ##########\n{text}\n")
with open(f"{base}/rytu_compiled_body.txt", "w", encoding="utf-8") as f:
    f.write(body)
with open(f"{base}/rytu_steps_render.txt", "w", encoding="utf-8") as f:
    f.write(render_steps(steps))
with open(f"{base}/rytu_wire.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=str)
print(json.dumps({k: v for k, v in out.items() if k not in ("wire", "call_instructions")}, ensure_ascii=False, indent=1, default=str))
