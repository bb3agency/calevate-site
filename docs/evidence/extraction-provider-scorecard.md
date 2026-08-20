# Extraction provider scorecard — EVIDENCE ARTIFACT

<!-- GENERATED FILE — do not hand-edit. -->
<!-- Regenerate: uv run python -m scripts.eval --client=ci --provider=offline --evidence=docs/evidence/extraction-provider-scorecard.md -->

Which extractor reads a Telugu code-mixed call transcript into CRM fields, scored on the golden-transcript fixtures (`tests/fixtures/golden_transcripts.json`) rather than on somebody else's leaderboard. The published benchmarks do not answer this question — nobody has published Telugu code-mixed call transcript → structured CRM fields — and this repo owns the right instrument, so the decision is made here.

Decisions: D-36 (canonical BYOK stack), D-15 (regression-on-every-change), and the residency argument that makes the provider choice more than a quality question. The gate this run feeds is task #87.

- Client: **ci**
- Vertical: all
- Run at: 2026-08-20T11:58:17.472236+00:00
- Cases per provider: 110

## Providers scored

| Provider | Model | Cases passed | Regressions against its own baseline |
|---|---|---|---|
| offline | `offline-heuristic` | 62/110 | none |

## Per field — the comparison that decides it

`right` is out of the cases that expected a value; `withheld` is out of the cases that expected silence. **WRONG** (a different non-null value) and **INVENTED** (a field the caller never mentioned) are called out because they are unwaivable on every model: a weaker model may miss a field, never file the wrong one. An empty cell means NOT MEASURED — it is never a zero.

| Field | offline |
|---|---|
| `bhk_size` | 15/16 right · 1 missed · 81/81 withheld |
| `budget_lakhs` | 0/9 right · 9 missed · 88/88 withheld |
| `callback_number` | 0/6 right · 6 missed · 104/104 withheld |
| `callback_time` | 0/6 right · 6 missed · 104/104 withheld |
| `intent` | 15/18 right · 3 missed · 81/81 withheld |
| `name` | 56/60 right · 4 missed · 50/50 withheld |
| `number_belongs_to` | 0/3 right · 3 missed · 105/105 withheld |
| `party_size` | 0/4 right · 4 missed · 106/106 withheld |
| `preferred_location` | 0/20 right · 20 missed · 77/77 withheld |
| `site_visit_interest` | 4/4 right · 93/93 withheld |
| `timeline` | 0/3 right · 3 missed · 93/93 withheld |
| `urgency` | 3/3 right · 103/103 withheld |
| `wants_callback` | 0/8 right · 8 missed · 93/93 withheld |

## What this run does NOT decide

- **Only one provider ran (offline).** This is a scorecard, not a comparison: nothing here says another extractor would do better or worse.
- **It cannot move the FIRST post-call extraction off Sarvam.** That pass reads the RAW transcript because a callback-number field needs the actual digits, and D-127 G-2/G-7 keeps it sovereign for that reason alone — `GEMINI_EXTRACTION_DEFAULT is False`, a constant D-410 deliberately did not move when it took both LLM surfaces to Azure OpenAI. An `azure` column that wins every field here changes what serves the user-triggered assist, over the REDACTED copy, and nothing else.
- **Residency is not a score.** Sending transcript text to a provider is a D-36 decision about where an Indian caller's words are processed, and no column here can outvote it.
- **The fixtures are synthetic.** They are the same cases for every provider, which is what makes the columns comparable, and they are not a sample of live traffic.
- **`compliance`, `redaction` and `fixture` failures score OUR code**, not the model's — a provider column carrying one of those is reporting a defect on this side of the seam.

## Failures, per provider

### offline (`offline-heuristic`)

- **Happy path — booking captured end to end** (`core5_happy_path`)
  - [capture_miss] missed party_size (expected 2)
- **Tool-call correctness — a valid slot, not an invented one** (`core5_tool_call`)
  - [capture_miss] missed intent (expected reschedule)
- **Out of scope (T4) — refuse, offer callback, tag for follow-up** (`core5_out_of_scope`)
  - [capture_miss] missed wants_callback (expected True)
- **Callback number read aloud digit by digit — the row the SMB acts on** (`callback_number_spoken_digits`)
  - [capture_miss] missed callback_number (expected ••99)
  - [capture_miss] missed callback_time (expected repu udayam pathi gantal…)
  - [capture_miss] missed number_belongs_to (expected self)
  - [capture_miss] missed wants_callback (expected True)
  - [outcome] outcome: expected needs_follow_up, got resolved
- **The number given belongs to a relative, not the caller** (`relative_number_attribution`)
  - [capture_miss] missed intent (expected book)
  - [capture_miss] missed callback_number (expected ••88)
  - [capture_miss] missed number_belongs_to (expected relative)
- **Hindi-mixed caller — a relative callback time (“kal subah”)** (`hindi_mixed_callback_time`)
  - [capture_miss] missed name (expected Imran)
  - [capture_miss] missed callback_time (expected kal subah)
  - [capture_miss] missed wants_callback (expected True)
  - [outcome] outcome: expected needs_follow_up, got resolved
- **Wrong number — nothing to file, and nothing may be invented** (`wrong_number_call`)
  - [outcome] outcome: expected dropped, got resolved
- **Hostile caller — an angry complaint, still no invented fields** (`hostile_caller_complaint`)
  - [outcome] outcome: expected needs_follow_up, got resolved
- **Silence — the caller says nothing and the line drops** (`silent_call`)
  - [outcome] outcome: expected dropped, got resolved
- **Native Telugu script — not everything arrives romanized** (`telugu_script_booking`)
  - [capture_miss] missed name (expected స్వాతి)
  - [capture_miss] missed intent (expected book)
  - [capture_miss] missed party_size (expected 3)
- **Real estate — a buyer qualified end to end (budget, locality, BHK, possession, site visit)** (`re_qualification_happy_path`)
  - [capture_miss] missed budget_lakhs (expected 50)
  - [capture_miss] missed preferred_location (expected Kondapur)
  - [capture_miss] missed timeline (expected aaru nelalo)
- **Real estate — tool-call correctness: a real site-visit slot, confirmed by the caller** (`re_site_visit_slot_confirmed`)
  - [capture_miss] missed preferred_location (expected Gachibowli)
  - [capture_miss] missed budget_lakhs (expected 80)
- **Real estate — out of scope (T4): loan EMI question refused, callback taken** (`re_home_loan_out_of_scope`)
  - [capture_miss] missed wants_callback (expected True)
- **Real estate — the callback number read aloud in Telugu digit words** (`re_whatsapp_number_spoken_digits`)
  - [capture_miss] missed budget_lakhs (expected 45)
  - [capture_miss] missed preferred_location (expected Miyapur)
  - [capture_miss] missed callback_number (expected ••77)
  - [capture_miss] missed callback_time (expected repu udayam)
  - [capture_miss] missed wants_callback (expected True)
- **Real estate — the caller declines the site visit and has no budget yet** (`re_undecided_declines_site_visit`)
  - [capture_miss] missed preferred_location (expected Manikonda)
- **Booking for three, counted in Telugu ('muggurum')** (`cl_book_three_people_telugu_count`)
  - [capture_miss] missed party_size (expected 3)
- **Hindi caller books — the name arrives in a form the pattern does not know** (`cl_book_hindi_caller`)
  - [capture_miss] missed name (expected Farhan)
- **The caller corrects themselves mid-sentence — the SECOND number wins** (`cl_book_self_corrected_party_size`)
  - [capture_miss] missed party_size (expected 3)
- **Callback number read aloud in English digit words** (`cl_book_callback_english_digits`)
  - [capture_miss] missed callback_number (expected ••66)
  - [capture_miss] missed callback_time (expected saayantram 4 taruvata | saayantram 4 gantala tar…)
- **Barge-in with crosstalk — half a sentence, and nothing else** (`cl_bargein_background_noise_partial`)
  - [outcome] outcome: expected dropped, got resolved
- **Out of scope (T4) — a blood report result the agent must not read out** (`cl_test_result_out_of_scope`)
  - [capture_miss] missed wants_callback (expected True)
- **Calling on behalf of a parent — whose number, and whose appointment** (`cl_calling_for_a_relative_third_party`)
  - [capture_miss] missed callback_number (expected ••88)
  - [capture_miss] missed number_belongs_to (expected relative)
- **An answering machine picks up — there is no caller at all** (`cl_ivr_machine_answered`)
  - [outcome] outcome: expected dropped, got resolved
- **Wrong number, in Hindi — nothing to file** (`cl_wrong_number_hindi`)
  - [outcome] outcome: expected dropped, got resolved
- **Out of scope — a pharmacy stock question, refused and tagged** (`cl_pharmacy_stock_question`)
  - [capture_miss] missed wants_callback (expected True)
- **Budget stated in CRORE — the unit conversion the column depends on** (`re_budget_in_crore`)
  - [capture_miss] missed budget_lakhs (expected 120)
  - [capture_miss] missed preferred_location (expected Jubilee Hills)
- **Budget given as a range — the template says take the upper figure** (`re_budget_range_upper_figure`)
  - [capture_miss] missed preferred_location (expected Nizampet)
  - [capture_miss] missed budget_lakhs (expected 55)
- **NRI buyer calling from abroad, in English, with a possession timeline** (`re_nri_caller_english`)
  - [capture_miss] missed preferred_location (expected Gachibowli)
  - [capture_miss] missed timeline (expected next year | next year, before march | by next year)
- **Hindi-speaking buyer — locality and size in a language the template never mentions** (`re_hindi_buyer_kukatpally`)
  - [capture_miss] missed name (expected Sunita)
  - [capture_miss] missed preferred_location (expected Kukatpally)
  - [capture_miss] missed budget_lakhs (expected 60)
- **An open-plot buyer — BHK does not apply and must stay empty** (`re_open_plot_not_a_flat`)
  - [capture_miss] missed preferred_location (expected Shadnagar)
  - [capture_miss] missed budget_lakhs (expected 60)
- **A four-bedroom villa — the enum's top bucket, spoken as words** (`re_villa_four_bhk_plus`)
  - [capture_miss] missed bhk_size (expected 4BHK+)
  - [capture_miss] missed preferred_location (expected Kokapet)
  - [capture_miss] missed budget_lakhs (expected 200)
- **The buyer refuses to state a budget — refusal is not a number** (`re_budget_refused`)
  - [capture_miss] missed preferred_location (expected Miyapur)
- **The number is read out, then corrected — both runs must be redacted, one must be filed** (`re_number_read_then_corrected`)
  - [capture_miss] missed preferred_location (expected Kompally)
  - [capture_miss] missed callback_number (expected ••88)
- **Barge-in — 'you called me yesterday too', without an opt-out** (`re_bargein_angry_about_repeat_calls`)
  - [outcome] outcome: expected needs_follow_up, got resolved
- **The agent offers a visit slot and the caller does not take it** (`re_site_visit_not_confirmed_yet`)
  - [capture_miss] missed preferred_location (expected Bachupally)
- **Two localities named, one of them explicitly ruled out** (`re_two_localities_one_rejected`)
  - [capture_miss] missed preferred_location (expected Kondapur)
- **Out of scope (T4) — registration charges and stamp duty** (`re_registration_charges_out_of_scope`)
  - [capture_miss] missed wants_callback (expected True)
- **Wrong number on an outbound property call** (`re_wrong_number_property`)
  - [outcome] outcome: expected dropped, got resolved
- **Outbound call answered and nobody speaks** (`re_silent_outbound_call`)
  - [outcome] outcome: expected dropped, got resolved
- **An existing buyer, furious about a delayed handover** (`re_hostile_delayed_possession`)
  - [outcome] outcome: expected needs_follow_up, got resolved
- **The caller refuses WhatsApp — a call consent is not a messaging consent** (`re_messaging_consent_declined`)
  - [capture_miss] missed preferred_location (expected Manikonda)
- **A callback time with no number attached to it** (`cl_callback_time_without_a_number`)
  - [capture_miss] missed callback_time (expected saayantram 7 taruvata | saayantram 7 gantala tar…)
- **An NRI states the budget in dollars — no conversion may be guessed** (`re_budget_stated_in_dollars`)
  - [capture_miss] missed preferred_location (expected Kokapet)
- **A resale enquiry — the caller wants a flat we are not selling** (`re_resale_not_new_project`)
  - [capture_miss] missed preferred_location (expected Kondapur)
- **'Ready to move' is a timeline in the caller's own words** (`re_ready_to_move_timeline`)
  - [capture_miss] missed preferred_location (expected Bachupally)
  - [capture_miss] missed timeline (expected ready to move | ippude)
- **The agent offers two projects; the caller picks one** (`re_two_projects_offered_one_chosen`)
  - [capture_miss] missed preferred_location (expected Nallagandla)
- **A property caller who only wants to be called later** (`re_callback_time_only_property`)
  - [capture_miss] missed callback_time (expected saayantram 6 taruvata | saayantram 6 gantala tar…)
- **Red team — a Telugu opt-out in the last minute, buried under a live requirement** (`rt_re_dnc_telugu_optout_late_and_mixed`)
  - [capture_miss] missed preferred_location (expected Kondapur)
  - [capture_miss] missed budget_lakhs (expected 60)
