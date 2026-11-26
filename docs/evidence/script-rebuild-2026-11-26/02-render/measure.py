"""Sizes of the rule and example text (read-only)."""
import importlib, inspect, json, re, sys
from calevate_shared import engine as E, call_script as C, spoken_style as SS

out = {}
cfg_txt = open(sys.argv[1] + "/rytu_instructions.txt", encoding="utf-8").read()
how = cfg_txt.split("LAYER how_to_speak")[1].split("##########", 2)[2].split("\n########## LAYER")[0]
out["how_to_speak_bullets"] = [(len(l), l[:70]) for l in how.strip().splitlines()]
notices = cfg_txt.split("LAYER notices")[1].split("##########", 2)[2].split("\n########## LAYER")[0]
out["notices_sentences"] = [(len(s), s[:70]) for s in re.split(r"(?<=[.?])\s+", notices.strip())]
for name in ["PROCEDURE_LEAD", "OUTCOMES_LEAD", "SCENARIO_LEAD", "SAY_EXACT_LINES", "SAY_EXACT_STEP",
             "PROCEDURE_POINTER", "SCENARIO_POINTER", "OUTCOME_IN_STEP", "ONE_DETAIL_PER_TURN",
             "ADHERENCE_SENTENCES"]:
    v = getattr(C, name)
    out[f"call_script.{name}"] = len(v) if isinstance(v, str) else {k: len(x) for k, x in v.items()}
for name in ["VOICE_STYLE_GUIDANCE", "OPENING_CONTINUES_RULE", "CALL_REASON_RULE", "PLACED_CALL_PERMISSION_RULE",
             "PLACED_CALL_OPENING_RULE", "CONFIDENTIALITY_RULE", "COLLECT_RULE", "CALL_BACK_TIME_RULE"]:
    v = getattr(E, name, None)
    if isinstance(v, str):
        out[f"engine.{name}"] = len(v)
# writer-side rule constants
for mod in ["apps.workers.campaign_script_ask", "apps.workers.script_assist", "apps.workers.campaign_script",
            "apps.api.agents.call_rules"]:
    try:
        m = importlib.import_module(mod)
    except Exception as exc:  # noqa: BLE001
        out[mod] = repr(exc); continue
    rows = {k: len(v) for k, v in vars(m).items() if k.isupper() and isinstance(v, str) and len(v) > 150}
    out[mod] = {"count": len(rows), "total": sum(rows.values()), "largest": sorted(rows.items(), key=lambda x: -x[1])[:25]}
# spoken style te-IN
st = SS.style_for("te-IN")
out["te.fillers"] = [(f.text, f.thinking) for f in st.fillers]
out["te.prompt_examples"] = [[(t.speaker, t.text) for t in ex] for ex in st.prompt_examples]
out["te.writer_example_sets"] = {k: len(v) for k, v in st.examples.items()}
out["te.register_guidance_len"] = len(SS.register_guidance("te-IN") or "")
out["te.prompt_example_line_len"] = len(SS.prompt_example_line("te-IN") or "")
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
