# Pip coverage matrix (D-938)

What a person can do or ask on each console screen, and which Pip tool answers it. One row per
distinct button or common question, client realm first, then admin. Columns: **Screen** (the
route under `/c/[slug]` or `/admin`), **Action or question**, **Pip tool:action** (client tools are
area tools, written `<area>_find:<read>` or `<area>_do:<action>`; admin tools are flat names),
**Tier**, **Status**. Tier rule: `now` runs at once and is reversible with Undo, spends nothing and
reaches no caller; `confirm` is everything else, and anything touching money, legal standing or an
irreversible result is always `confirm`; `read` answers only; `nav` is `open_screen`. A MISSING row's
tier is the tier the tool should get. NEVER rows stay screen only (legal acceptances, the
no-cold-calls pledge, KYC documents and DigiLocker, payments and autopay mandates, OAuth sign-ins,
emailed codes, the person's own consent records, deleting the account). `apps/api/copilot/areas.py`
(`ENTRIES`) is the source of truth for client tools; `admin_tools.py` and `admin_actions.py` for admin.

Status: COVERED, MISSING, NEVER, NAV, BUILT (D-938), OWNED ELSEWHERE (D-934 reports/charts,
D-935 troubleshooting and line-protection healer, D-936 proactive notes, D-937 Pip quality scores).

## Client realm

### Every screen

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| any | "Take me to X" / open a screen | open_screen | nav | COVERED |
| any | "How do I ...?" (help entry and the screen) | settings_find:help_lookup | read | BUILT (D-938) |
| any | Turn Pip on or off for the account | screen only | - | NEVER (screen only: the owner's own consent record) |
| any | "Why is my line down / what's wrong?" | troubleshooting | - | OWNED ELSEWHERE (D-935) |
| any | Pip speaks up unprompted with a note | proactive notes | - | OWNED ELSEWHERE (D-936) |
| any | Thumbs up/down on a Pip answer | quality scores | - | OWNED ELSEWHERE (D-937) |
| any | Dismiss an announcement | (none) | now | MISSING |
| any | Mark notifications read | (none) | now | MISSING |

### Home `/c/[slug]`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| home | "How many calls/leads today/this week?" | reports_find:business_snapshot | read | COVERED |
| home | "What needs my attention?" | reports_find:needs_attention | read | COVERED |
| home | "Any calls right now?" | calls_find:calls_live | read | COVERED |
| home | "What's my balance?" | billing_find:billing_overview | read | COVERED |
| home | Place a free-trial test call | agents_do:agent_test_call | confirm | COVERED |
| home | Pin a chart to the dashboard | reports | - | OWNED ELSEWHERE (D-934) |
| home | Retry a call's English | calls_do:call_translate | confirm | COVERED |
| home | Setup checklist step ("what's left to go live?") | settings_find:verification_status | read | COVERED |

### Attention `/attention`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| attention | "What needs attention?" | reports_find:needs_attention | read | COVERED |
| attention | Mark a call resolved / needs-you | calls_do:call_follow_up_set | now | COVERED |
| attention | Call the person back now | calls_do:call_back | confirm | COVERED |

### Agents list `/agents`, new agent `/agents/new`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| agents | "Which agents are live?" | agents_find:agents_list | read | COVERED |
| agents | "Which voices can I use?" | agents_find:voices_offered | read | COVERED |
| agents | Create an agent | agents_do:agent_create | now | COVERED |
| agents | Rename an agent | agents_do:agent_rename | now | COVERED |
| agents | Pause a live agent | agents_do:agent_deactivate | confirm | COVERED |
| agents | Delete an agent | agents_do:agent_delete | confirm | COVERED |
| agents | Restore a deleted agent | agents_do:agent_restore | now | COVERED |
| agents | Rewrite the opening line in another language | agents_do:agent_edit / agent_edit_live | now / confirm | COVERED |
| agents | Account default AI model tier | settings_do:account_model_tier_set | confirm | BUILT (D-938) |

### First agent `/agents/first`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| first agent | Write the brief / answer follow-up questions | agents_do:agent_script_suggest (whole) | confirm | COVERED |
| first agent | Add a document to the brief | knowledge_do:knowledge_teach | confirm | COVERED |
| first agent | Remove a brief document | knowledge_do:knowledge_remove | confirm | COVERED |
| first agent | Rename the agent | agents_do:agent_rename | now | COVERED |
| first agent | Replace the opening line | agents_do:agent_edit | now | COVERED |
| first agent | Build the agent | agents_do:agent_prepare | confirm | COVERED |
| first agent | Place a trial call | agents_do:agent_test_call | confirm | COVERED |
| first agent | Accept an agreement | screen only | - | NEVER (legal acceptance) |
| first agent | Accept the no-cold-calls pledge | screen only | - | NEVER (legal pledge) |
| first agent | Turn Pip on | screen only | - | NEVER (owner's own consent) |
| first agent | Dismiss / finish first run | (none) | now | MISSING |
| first agent | Hear a spoken piece of the brief | (none) | read | MISSING |

### Agent workspace `/agents/[agentId]` (overview, script, training, settings, delivery, try it)

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| agent | "Tell me about this agent" | agents_find:agent_detail | read | COVERED |
| agent | "Show its call handling / handover / actions" | agents_find:agent_settings | read | COVERED |
| agent | "What does it know / look up?" | knowledge_find:agent_known_facts | read | COVERED |
| agent | Put it live | agents_do:agent_publish | confirm | COVERED |
| agent | Ready to try in chat | agents_do:agent_prepare | confirm | COVERED |
| agent | Pause it | agents_do:agent_deactivate | confirm | COVERED |
| agent | Edit language, voice, opening line, notices (draft/paused) | agents_do:agent_edit | now | COVERED |
| agent | Same for a live agent | agents_do:agent_edit_live | confirm | COVERED |
| agent | AI disclosure / recording notice switches | agents_do:agent_edit / agent_edit_live | now / confirm | COVERED |
| script | Suggest a script change / whole script / steps | agents_do:agent_script_suggest | confirm | COVERED |
| script | Save and put the reviewed draft live | agents_do:agent_script_put_live | confirm | COVERED |
| script | Apply a staged change | agents_do:agent_changes_apply | confirm | COVERED |
| script | Discard a staged change | agents_do:agent_script_discard | confirm | COVERED |
| script | Restore an earlier version | agents_do:agent_script_version_restore | confirm | COVERED |
| script | "What changed between versions?" | (none) | read | MISSING |
| script | Add or dismiss a proposed rule | (none) | confirm | MISSING |
| script | Clear a suggestion once its parts are kept | (none) | now | MISSING |
| training | Run practice tests | agents_do:agent_tests_run | confirm | COVERED |
| training | Fix failed tests | agents_do:agent_tests_fix | confirm | COVERED |
| training | Save a hand-written test | agents_do:agent_test_add | now | COVERED |
| training | Make a call into a test | calls_do:call_test_prepare | now | COVERED |
| training | Delete a saved test | (none) | now | MISSING |
| training | Mark a failed test as wrong | (none) | now | MISSING |
| training | Settle / apply suggested improvements | agents_do:agent_tests_fix | confirm | COVERED |
| training | Answer the agent's open questions | knowledge_do:knowledge_question_settle | confirm | COVERED |
| settings | Speed, loudness, tone, pauses, nudges, ambience, longest call, AI model, caller memory, screen guide | agents_do:agent_settings_set | confirm | COVERED |
| settings | Use these call settings on every agent | agents_do:agent_settings_set (scope all_agents) | confirm | COVERED |
| settings | Hear a Studio voice preview | (none) | read | MISSING |
| settings | Handover list | agents_do:agent_handover_set | confirm | COVERED |
| settings | Add / change an in-call action | agents_do:agent_action_set | confirm | COVERED |
| settings | Switch an action (or all) on/off | agents_do:agent_action_switch | confirm | COVERED |
| settings | Remove an in-call action | agents_do:agent_action_remove | confirm | COVERED |
| settings | Run an in-call action once with sample values | (none) | confirm | MISSING |
| settings | When the agent tells the team about a caller | agents_do:agent_team_alert_set | confirm | BUILT (D-938) |
| delivery | Details it writes down (draft/paused) | agents_do:agent_capture_fields_set | now | COVERED |
| delivery | Same for a live agent | agents_do:agent_capture_fields_set_live | confirm | COVERED |
| delivery | Accept / turn down a lead-detail suggestion | agents_do:lead_suggestion_answer | confirm | COVERED |
| delivery | Call outcomes: AI draft / replace | (none) | confirm | MISSING |
| known facts | Add, edit, pin, unpin, remove a fact | knowledge_do:knowledge_fact_change | confirm | COVERED |
| try it | Chat with the agent as a caller | (none) | read | MISSING |
| try it | Trial call to my phone | agents_do:agent_test_call | confirm | COVERED |
| agent | "How much does this agent cost a minute?" | agents_find:agent_settings | read | COVERED |

### Calls `/calls`, call detail `/calls/[callId]`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| calls | "Calls today / missed / by agent" | calls_find:calls_recent | read | COVERED |
| calls | "Who asked about X?" | calls_find:search_calls | read | COVERED |
| calls | "Live calls now" | calls_find:calls_live | read | COVERED |
| calls | Export calls | calls_do:calls_export | confirm | COVERED |
| calls | Save / rename / delete a call view | (none) | now | MISSING |
| calls | Mark follow-up done / needs-you | calls_do:call_follow_up_set | now | COVERED |
| calls | Call back many unanswered | calls_do:calls_place_bulk | confirm | COVERED |
| call | "Summarise this call" / read it | calls_find:call_detail | read | COVERED |
| call | Summarise again | calls_do:call_summarise_again | confirm | COVERED |
| call | Translate to English again | calls_do:call_translate | confirm | COVERED |
| call | Call them back now with context | calls_do:call_back | confirm | COVERED |
| call | Book a call-back | callbacks_do:callback_book | confirm | COVERED |
| call | Send an approved WhatsApp | calls_do:lead_whatsapp_send | confirm | COVERED |
| call | Make it a test | calls_do:call_test_prepare | now | COVERED |
| call | Discard the test Pip prepared | (none) | now | MISSING |
| call | Read the raw transcript (owner, audited) | calls_find:call_detail (redacted only) | read | MISSING |
| call | Play / download the recording | open_screen | nav | NAV |
| call | Add a fact the caller needed | knowledge_do:propose_knowledge | confirm | COVERED |

### Leads `/leads`, lead detail `/leads/[leadId]`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| leads | "Show hot leads from last week" | leads_find:leads_search | read | COVERED |
| leads | "Who asked for X?" | leads_find:leads_semantic_search | read | COVERED |
| leads | Change one lead's status | leads_do:lead_set_status | now | COVERED |
| leads | Change status/owner of many | leads_do:leads_bulk_update | confirm | COVERED |
| leads | Assign to a team member | leads_do:lead_assign | now | COVERED |
| leads | Correct a name | leads_do:lead_rename | confirm | COVERED |
| leads | Save a view | leads_do:lead_view_save | now | COVERED |
| leads | Rename / delete a saved view | (none) | now | MISSING |
| leads | Export to a spreadsheet | leads_do:leads_export | confirm | COVERED |
| leads | Add to a campaign | campaigns_do:campaign_add_leads | confirm | COVERED |
| leads | Call many now | calls_do:calls_place_bulk | confirm | COVERED |
| leads | Book call-backs for many | callbacks_do:callbacks_book_bulk | confirm | COVERED |
| lead | "Tell me about this lead" | leads_find:lead_detail | read | COVERED |
| lead | Call now | calls_do:call_place | confirm | COVERED |
| lead | Call back later | callbacks_do:callback_book | confirm | COVERED |
| lead | WhatsApp them | calls_do:lead_whatsapp_send | confirm | COVERED |
| lead | Stop calling this number | leads_do:dnc_add | confirm | COVERED |
| lead | Edit a captured detail value | (none) | confirm | MISSING |
| leads | Start picked or filtered leads on a Follow-up | leads_do:follow_up_start | confirm | BUILT (D-940) |

### Follow-ups `/follow-ups`, detail `/follow-ups/[followUpId]` (D-940)

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| follow-ups | "Which Follow-ups are on?" / the ready-made ones | leads_find:follow_ups_list | read | BUILT (D-940) |
| follow-up | "What does this one do / who is in it?" | leads_find:follow_up_read | read | BUILT (D-940) |
| follow-ups | New Follow-up from a sentence | leads_do:follow_up_draft | confirm | BUILT (D-940) |
| follow-ups | New from a ready-made one (explains what is missing) | leads_do:follow_up_draft (starter) | confirm | BUILT (D-940) |
| follow-up | "Ask Pip to change it" (rewrite the draft) | leads_do:follow_up_draft (follow_up_id) | confirm | BUILT (D-940) |
| follow-up | Small edits: a wait, a message, the agent, remove a step | leads_do:follow_up_draft (follow_up_id) | confirm | BUILT (D-940) |
| follow-up | Publish | leads_do:follow_up_publish | confirm | BUILT (D-940) |
| follow-up | Pause (Undo resumes) | leads_do:follow_up_pause | confirm | BUILT (D-940) |
| follow-up | Resume / turn back on (Undo puts it back) | leads_do:follow_up_resume | confirm | BUILT (D-940) |
| follow-up | Turn off | leads_do:follow_up_turn_off | confirm | BUILT (D-940) |
| follow-up | Stop one lead's run | (none) | confirm | MISSING |
| follow-up | "How is it doing?" (results by step) | leads_find:follow_up_read (counts) | read | BUILT (D-940) |

### Call-backs `/callbacks`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| callbacks | "Which call-backs are due?" | callbacks_find:callbacks_list | read | COVERED |
| callbacks | Move one | callbacks_do:callback_reschedule | confirm | COVERED |
| callbacks | Cancel one | callbacks_do:callback_cancel | confirm | COVERED |
| callbacks | Move or cancel many | callbacks_do:callbacks_change_bulk | confirm | COVERED |

### Campaigns `/campaigns`, new, edit, detail

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| campaigns | "How are my campaigns doing?" | campaigns_find:campaigns_list | read | COVERED |
| campaign | "Why can't this launch?" | campaigns_find:campaign_detail | read | COVERED |
| campaigns | New draft | campaigns_do:campaign_create | now | COVERED |
| campaigns | Duplicate | campaigns_do:campaign_clone | now | COVERED |
| campaign | Edit name, agent, pace, hours, tries | campaigns_do:campaign_edit | now | COVERED |
| campaign | Add leads | campaigns_do:campaign_add_leads | confirm | COVERED |
| campaign | Add a pasted/attached list (CSV) | campaigns_do:campaign_contacts_add | confirm | COVERED |
| campaign | Remove people | campaigns_do:campaign_contacts_remove | confirm | COVERED |
| campaign | Declare where consent came from | campaigns_do:campaign_consent_set | confirm | COVERED |
| campaign | Launch | campaigns_do:campaign_launch | confirm | COVERED |
| campaign | Schedule / cancel schedule | campaigns_do:campaign_schedule / campaign_unschedule | confirm | COVERED |
| campaign | Repeat weekly | campaigns_do:campaign_repeat | confirm | COVERED |
| campaign | Pause / resume | campaigns_do:campaign_pause / campaign_resume | confirm | COVERED |
| campaign | Stop for good | campaigns_do:campaign_stop | confirm | COVERED |
| campaign | Delete a draft | campaigns_do:campaign_delete | confirm | COVERED |
| campaign | Confirm the complaint review | screen only | - | NEVER (legal attestation by a human) |
| campaign | "Results per contact / opt-outs" | campaigns_find:campaign_detail | read | COVERED |

### Knowledge `/knowledge`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| knowledge | "What do the agents tell callers about X?" | knowledge_find:search_knowledge | read | COVERED |
| knowledge | "What files, links, notes are there?" | knowledge_find:knowledge_sources | read | COVERED |
| knowledge | "What questions are unanswered?" | knowledge_find:knowledge_questions | read | COVERED |
| knowledge | Add one fact | knowledge_do:propose_knowledge | confirm | COVERED |
| knowledge | Teach from typed text / attachment | knowledge_do:knowledge_teach | confirm | COVERED |
| knowledge | Add a web page | knowledge_do:knowledge_link_add | confirm | COVERED |
| knowledge | Upload a document or photo | knowledge_do:knowledge_teach (Pip attachment) | confirm | COVERED |
| knowledge | Rename a file/link/note | knowledge_do:knowledge_rename | now | COVERED |
| knowledge | Edit a note / correcting note | knowledge_do:knowledge_note_save | confirm | COVERED |
| knowledge | Remove / restore | knowledge_do:knowledge_remove | confirm | COVERED |
| knowledge | Edit, pin, unpin, move a fact | knowledge_do:knowledge_fact_change | confirm | COVERED |
| knowledge | Pin three questions | knowledge_do:knowledge_facts_pin | confirm | COVERED |
| knowledge | Answer or dismiss a question | knowledge_do:knowledge_question_settle | confirm | COVERED |
| knowledge | Approve a waiting upload / read a PDF or link again | knowledge_do:knowledge_refresh | confirm | BUILT (D-938) |
| knowledge | Let staff curate knowledge | settings_do:account_switch_set | confirm | BUILT (D-938) |
| knowledge | Discard a teaching in review | (none) | now | MISSING |
| knowledge | Voice-note into the teach box | screen only | - | NAV |

### Numbers `/phone-number`, `/settings/phone-numbers`, `/setup/existing-number`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| numbers | "Which numbers do I have?" | numbers_find:numbers_list | read | COVERED |
| numbers | "Which cities have numbers?" | numbers_find:numbers_available | read | COVERED |
| numbers | Buy a number | numbers_do:number_buy | confirm | COVERED |
| numbers | Release a number | numbers_do:number_release | confirm | COVERED |
| numbers | Assign a number to an agent | numbers_do:number_assign | confirm | COVERED |
| numbers | Record who numbers are registered to | (none) | confirm | MISSING |
| numbers | Send verified business details for numbers | (none) | confirm | MISSING |
| forwarding | Track an existing number | numbers_do:forwarding_line_add | confirm | COVERED |
| forwarding | Change how it forwards | numbers_do:forwarding_line_change | now | COVERED |
| forwarding | Stop tracking it | numbers_do:forwarding_line_remove | confirm | COVERED |
| forwarding | Test call it | numbers_do:forwarding_line_test | confirm | COVERED |
| forwarding | Save-our-number WhatsApp on/off | settings_do:account_switch_set | confirm | BUILT (D-938) |

### Lead sources `/lead-sources`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| lead sources | "Are my lead sources working?" | integrations_find:integrations_status | read | COVERED |
| lead sources | New lead source | integrations_do:lead_source_create | confirm | COVERED |
| lead sources | Which agent answers it | integrations_do:lead_source_edit | confirm | COVERED |
| lead sources | Pause / resume | integrations_do:lead_source_switch | confirm | COVERED |
| lead sources | New secret | integrations_do:lead_source_rotate | confirm | COVERED |
| lead sources | Field mapping | integrations_do:lead_source_mapping | confirm | COVERED |
| lead sources | When and how new leads are called | integrations_do:lead_calling_rules | confirm | COVERED |
| lead sources | Call or drop a held lead | integrations_do:held_lead_decide | confirm | COVERED |
| lead sources | Send a test lead (dry run) | (none) | confirm | MISSING |
| lead sources | Re-run unread Meta leads | (none) | confirm | MISSING |
| lead sources | Meta Lead Ads set-up | screen only | - | NEVER (OAuth / Meta sign-in) |

### Integrations `/integrations`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| integrations | "Which connections failed?" | integrations_find:integrations_status | read | COVERED |
| integrations | New webhook endpoint | integrations_do:crm_endpoint_create | confirm | COVERED |
| integrations | Change endpoint events | integrations_do:crm_endpoint_edit | confirm | COVERED |
| integrations | Switch endpoint off / re-key | integrations_do:crm_endpoint_act | confirm | COVERED |
| integrations | Resend a failed delivery | integrations_do:crm_delivery_resend | confirm | COVERED |
| integrations | Check a connected account still works | integrations_find:connection_check | read | BUILT (D-938) |
| integrations | Disconnect a connected account | integrations_do:connection_disconnect | confirm | BUILT (D-938) |
| integrations | Rotate a stored credential | (none) | confirm | MISSING |
| integrations | Google Sheets endpoint (picker) | screen only | - | NEVER (Google OAuth picker) |
| integrations | Connect Google Calendar / Zoho / HubSpot | screen only | - | NEVER (OAuth sign-in) |
| integrations | Connect WhatsApp (Embedded Signup) | screen only | - | NEVER (OAuth sign-in) |
| integrations | Disconnect / finish a WhatsApp account | (none) | confirm | MISSING |
| integrations | Write a WhatsApp template for review | (none) | confirm | MISSING |
| integrations | "What did delivery X send?" | (none) | read | MISSING |

### Billing `/billing` (credits, statements, usage), `/ai-assist`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| billing | "What's my balance / statements?" | billing_find:billing_overview | read | COVERED |
| billing | "What are my limits / auto-recharge?" | billing_find:billing_settings | read | COVERED |
| billing | "Where did my money go this month?" | reports_find:business_snapshot | read | COVERED |
| billing | Spending and minute limits | billing_do:spend_caps_set | confirm | COVERED |
| billing | Auto-recharge amounts on/off | billing_do:auto_recharge_set | confirm | COVERED |
| billing | Low-credit warning | billing_do:low_balance_alert_set | now | COVERED |
| billing | "Take me to top up" | open_screen | nav | NAV |
| billing | Top up / checkout | screen only | - | NEVER (payment) |
| billing | Approve / withdraw autopay mandate | screen only | - | NEVER (payment mandate) |
| billing | Pay the platform fee | screen only | - | NEVER (payment) |
| billing | Print / download a statement or receipt | open_screen | nav | NAV |
| billing | "Clear vs Studio cost per minute?" | (none) | read | MISSING |
| ai-assist | "How much AI help is left?" | (none) | read | MISSING |
| ai-assist | Buy extra AI help this month (from credit) | billing_do:ai_allowance_extra | confirm | COVERED |

### Settings

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| business | Opening hours | settings_do:business_hours_set | confirm | COVERED |
| business | Branches, services, FAQs, staff, rules, languages | settings_do:business_profile_set | confirm | COVERED |
| business | Rewrite the account's examples | settings_do:business_copy_refresh | confirm | COVERED |
| business | "What's in my business profile?" | knowledge_find:knowledge_sources | read | COVERED |
| models | Account default AI model tier | settings_do:account_model_tier_set | confirm | BUILT (D-938) |
| team | "Who is on the team?" | team_find:team_members | read | COVERED |
| team | Invite | team_do:team_invite | confirm | COVERED |
| team | Change role | team_do:team_member_role | confirm | COVERED |
| team | Remove member | team_do:team_member_remove | confirm | COVERED |
| team | Resend / cancel invitation | team_do:team_invitation | confirm | COVERED |
| team | Add / remove / make default a team alert address | team_do:team_alert_contact | confirm | BUILT (D-938) |
| team | Verify a team address with its emailed code | screen only | - | NEVER (emailed verification code) |
| alerts | My WhatsApp hot-lead alerts on/off | screen only | - | NEVER (person's own consent record) |
| alerts | Desktop alerts on/off | screen only | - | NEVER (browser permission prompt) |
| lead details | Draft a custom business's lead details | settings_do:lead_fields_draft | confirm | COVERED |
| lead details | Keep some drafted details | agents_do:lead_fields_keep_draft | confirm | COVERED |
| lead details | Back to the standard set | agents_do:lead_fields_reset | confirm | COVERED |
| lead details | Accept / turn down a suggestion | agents_do:lead_suggestion_answer | confirm | COVERED |
| call-handling | Account default call settings | agents_do:agent_settings_set (scope all_agents) | confirm | COVERED |
| line protection | Backup phone set / remove | settings_do:line_protection_phone | confirm | COVERED |
| line protection | Turn my line back on (restore incident) | healer | - | OWNED ELSEWHERE (D-935) |
| line protection | Apply / dismiss a suggested change | healer | - | OWNED ELSEWHERE (D-935) |
| verify | "What verification is still needed?" | settings_find:verification_status | read | COVERED |
| verify | Save business legal details (GST, owner) | (none) | confirm | MISSING |
| verify | Upload KYC document / submit for review | screen only | - | NEVER (KYC documents) |
| verify | DigiLocker verification | screen only | - | NEVER (DigiLocker) |
| verify | No-cold-calls pledge | screen only | - | NEVER (legal pledge) |
| agreements | Accept an agreement | screen only | - | NEVER (legal acceptance) |
| agreements | "Which agreements are pending?" | settings_find:verification_status | read | COVERED |
| setup | Setup wizard step: save profile | settings_do:business_profile_set | confirm | COVERED |
| setup | Skip / dismiss a wizard step | (none) | now | MISSING |
| go-live | Finish / dismiss go-live guide | (none) | now | MISSING |
| go-live | "What's left before going live?" | settings_find:verification_status | read | COVERED |
| account | Delete the account | screen only | - | NEVER (deleting the account) |

### Routines (Pip), compliance screens, reports

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| assistant | "What routines do I have?" | routines_find:routines_list | read | COVERED |
| assistant | Create a routine | routines_do:routine_create | confirm | COVERED |
| assistant | Change, pause, resume | routines_do:routine_edit | confirm | COVERED |
| assistant | Delete | routines_do:routine_delete | confirm | COVERED |
| assistant | Run a routine once now | (none) | confirm | MISSING |
| do-not-call | Stop calling one lead | leads_do:dnc_add | confirm | COVERED |
| do-not-call | Add arbitrary numbers (not leads) | (none) | confirm | MISSING |
| do-not-call | "Is this number blocked?" | (none) | read | MISSING |
| do-not-call | Remove a hand-added entry | leads_do:dnc_remove | confirm | COVERED |
| do-not-call | Restore a person's opt-out on their word | leads_do:dnc_restore | confirm | COVERED |
| do-not-call | Require an opt-in before dialling | settings_do:account_switch_set | confirm | BUILT (D-938) |
| do-not-call | Record a customer's call consent | (none) | confirm | MISSING |
| messaging-consent | "May we message this number?" | (none) | read | MISSING |
| messaging-consent | Record what a customer said about messages | (none) | confirm | MISSING |
| data-rights | File an erasure request for a number | (none) | confirm | MISSING |
| data-rights | Subject access export for a number | (none) | confirm | MISSING |
| caller-notice | Fill and print the caller notice | open_screen | nav | NAV |
| performance | "Busiest hours / call lengths / by agent" | reports_find:business_snapshot | read | COVERED |
| performance | Chart it / pin it | reports | - | OWNED ELSEWHERE (D-934) |
| quality | "How did the agents score?" | reports_find:quality_reports | read | COVERED |

## Admin realm

Admin tools are flat. With a client's account open, every client READ tool (e.g. `agents_list`,
`calls_recent`, `billing_overview`) is also a flat admin tool; no client action is.

### Platform screens

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| any | "Take me to X" | open_screen (admin) | nav | COVERED |
| any | "How do I handle X?" (runbooks) | search_runbooks | read | COVERED |
| home | "Which clients exist / how active?" | platform_tenants | read | COVERED |
| home | "Unfinished onboardings" | platform_tenants | read | COVERED |
| home | Record TM registration | (none) | confirm | MISSING |
| new | Create a client account | (none) | confirm | MISSING |
| health | "Which clients are unhealthy?" | platform_health | read | COVERED |
| holds | "Which accounts are held?" | admin_held_accounts | read | COVERED |
| kyc-reviews | "What's in the KYC queue?" | admin_kyc_queue | read | COVERED |
| ops | "Is outbound halted / platform state?" | platform_ops_state | read | COVERED |
| ops | Halt all outbound (big red switch) | platform_halt_outbound | confirm | COVERED |
| ops | Resume outbound | (none) | confirm | MISSING |
| ops | Attest engine minute price | healer_attest_rate | confirm | COVERED |
| ops | Attest model / LLM / TTS / number / embedding prices, FX, data-use | (none) | confirm | MISSING |
| ops | "What are the credit-pack rates and margins?" | admin_rate_card | read | BUILT (D-938) |
| ops | Record / cancel a rate card | (none) | confirm | MISSING |
| ops | Set / test / remove a secret | screen only | - | NEVER (secrets entry) |
| ops | Re-wrap KEKs | screen only | - | NEVER (irreversible key operation, step-up) |
| ops | Verify audit chain | (none) | read | MISSING |
| ops | Replay outbox / KB orphan check | (none) | confirm | MISSING |
| ops/config | "What's this config value?" | (none) | read | MISSING |
| ops/config | Set / revert a config row | (none) | confirm | MISSING |
| ops/config | Set up the trial line | (none) | confirm | MISSING |
| ops/alerts | "What alerts fired?" | admin_alerts | read | COVERED |
| ops/alerts | Re-copy a recording | (none) | confirm | MISSING |
| ops/dnc | Find a number on the global DNC | (none) | read | MISSING |
| ops/dnc | Suppress / release globally | (none) | confirm | MISSING |
| ops/healer | "Open healer incidents?" | healer_incidents / healer_incident | read | COVERED |
| ops/healer | "Money problems to review?" | healer_money_review | read | COVERED |
| ops/healer | Retry an incident | healer_retry | confirm | COVERED |
| ops/healer | Resolve an incident | healer_resolve | confirm | COVERED |
| ops/healer | Post a status update | (none) | confirm | MISSING |
| ops/maintenance | Schedule / amend / cancel / end maintenance | (none) | confirm | MISSING |
| ops/reply-times | "How fast are replies?" | (none) | read | MISSING |
| ops/spoken-style | Change / publish spoken style | (none) | confirm | MISSING |
| ops/voices | "Which voices are hosted?" | admin_voices | read | COVERED |
| ops/voices | Enable / disable / archive a voice | admin_voice_set | confirm | COVERED |
| ops/voices | Clone a voice / delete a clone / record consent | screen only | - | NEVER (voice owner's consent record and audio upload) |
| ops/voices | Rename voice, add hosted voice, refresh catalogue | (none) | confirm | MISSING |
| ops/voices | Studio voices / own-model switches | (none) | confirm | MISSING |
| ops/whatsapp | "WhatsApp accounts state" | (none) | read | MISSING |
| payments | "Recent payments / disputes" | (none) | read | MISSING |
| payments | Accept / contest a dispute | screen only | - | NEVER (payment dispute, money) |
| payments | Run reconciliation | (none) | confirm | MISSING |
| qa-sampling | "Next sample waiting" | (none) | read | MISSING |
| qa-sampling | Review a QA sample | (none) | confirm | MISSING |
| spend | "Fleet spend / TTS speaking rate" | (none) | read | MISSING |
| operators | Add / revoke / change role / resend setup link | (none) | confirm | MISSING |
| announcements | Create / edit / end announcement | (none) | confirm | MISSING |
| view-as | View a client's console | open_screen (admin) | nav | NAV |

### One client `/admin/tenants/[tenantId]/**`

| Screen | Action or question | Pip tool:action | Tier | Status |
|---|---|---|---|---|
| tenant | "Where does this client stand (KYC, trial, dial block)?" | admin_client_standing | read | COVERED |
| tenant | Client's calls, leads, agents, balance | client read tools (flat) | read | COVERED |
| tenant | Business type confirm / suggest again | (none) | confirm | MISSING |
| tenant | KB queue decision (approve/reject upload) | (none) | confirm | MISSING |
| tenant | DLT registration / template / number DLT status | (none) | confirm | MISSING |
| tenant | Recompute spend cap | (none) | confirm | MISSING |
| tenant | Record client alert opt-in | screen only | - | NEVER (a person's consent record) |
| activity | "What happened on this account?" | (none) | read | MISSING |
| agents | "Which agents, which model?" | agents_list (flat) | read | COVERED |
| agent prompt | "Show the prompt history" | (none) | read | MISSING |
| call-handling | Set client's call handling | (none) | confirm | MISSING |
| closure | Close / restore / erase account | screen only | - | NEVER (deleting the account) |
| commercials | Record terms / fee payment / fee waiver | (none) | confirm | MISSING |
| credits | Grant credits / refund / adjustment / top-up record | (none) | confirm | MISSING |
| credits | Start / end trial / make paid | (none) | confirm | MISSING |
| dnd-scrub | Record a preference scrub | (none) | confirm | MISSING |
| feature-flags | Set a feature flag | (none) | confirm | MISSING |
| invoice | Print an invoice | open_screen (admin) | nav | NAV |
| kyc | Approve / reject KYC | admin_kyc_review | confirm | COVERED |
| kyc | Record KYC / set DigiLocker requirement | (none) | confirm | MISSING |
| kyc | Refresh workspace business details | (none) | confirm | MISSING |
| lead-details | Draft / replace / save lead details | (none) | confirm | MISSING |
| lifecycle | Set tenant status | (none) | confirm | MISSING |
| llm-model | Set client's default model | (none) | confirm | MISSING |
| members | Invite / resend / revoke / role / remove | (none) | confirm | MISSING |
| numbers | Provision a workspace | admin_workspace_provision | confirm | COVERED |
| numbers | Release a number | admin_number_release | confirm | COVERED |
| numbers | Buy / record / assign / move / forget numbers, call lines | (none) | confirm | MISSING |
| numbers | Offboard workspace | (none) | confirm | MISSING |
| profile | Edit tenant profile | (none) | confirm | MISSING |
| readiness | "Is this client ready?" | admin_client_standing | read | COVERED |
| spend | "Client spend / cache share" | billing_overview (flat) | read | COVERED |

## MISSING, ranked (most-asked first, after D-938)

1. Saved views: rename/delete lead views; save/rename/delete call views (`leads_do`, `calls_do`, now).
2. "Is this number blocked?" DNC check, and add arbitrary numbers to DNC (`leads_find`/`leads_do`).
3. "May we message / call this number?" consent lookup (read) and recording a customer's consent (confirm).
4. Raw transcript read for the owner, audited (`calls_find`, role-gated).
5. "How much AI help is left?" quota read (`billing_find`).
6. Practice tests: delete a saved test, mark a failed test wrong (`agents_do`, now).
7. Call outcomes per agent: AI draft and replace (`agents_do`, confirm).
8. Script: compare versions (read), add/dismiss proposed rules, clear a kept suggestion.
9. Run a routine once now (`routines_do`, confirm).
10. Lead sources: send a test lead, re-run unread Meta leads (`integrations_do`, confirm).
11. WhatsApp: write a template for review, disconnect/finish an account (`integrations_do`, confirm).
12. Run an in-call action once with sample values; Studio voice preview (`agents_do`/`agents_find`).
13. Clear vs Studio per-minute comparison (`billing_find`).
14. Verify-business legal details save; numbers holder record and business details send (confirm).
15. Data rights: erasure request and subject export for one number (confirm).
16. Small UI acts: dismiss announcement, mark notifications read, wizard/go-live/first-run dismiss.
17. Admin: resume outbound, config read/set/revert, recording a rate card, price attestations, global DNC,
    maintenance, operators, announcements, payments/QA/spend reads, and per-client writes
    (credits, trial, members, numbers, feature flags, lifecycle, model, lead details).
