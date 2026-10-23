"use client";

import { useState } from "react";

import { DatePicker, DateRangePicker, Calendar, type DateRange } from "@/components/arc/calendar";
import { ChipGroup } from "@/components/arc/chip-group";
import { Combobox } from "@/components/arc/combobox";
import { InlineEdit } from "@/components/arc/inline-edit";
import { addDays, todayIST } from "@/components/arc/ist-dates";
import { MoneyInput } from "@/components/arc/money-input";
import { MultiSelect } from "@/components/arc/multi-select";
import { NumberField } from "@/components/arc/number-field";
import { PeriodToggle, type Period } from "@/components/arc/period-toggle";
import { RadioGroup } from "@/components/arc/radio-group";
import { ExpandingSearch, SearchField } from "@/components/arc/search-field";
import { RangeSlider, Slider } from "@/components/arc/slider";
import { TagInput } from "@/components/arc/tag-input";
import type { FeedbackStatus } from "@/components/arc/feedback";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ToggleSwitch } from "@/components/ui";

import { KitDemo, KitGrid, KitSection } from "../kitLayout";

const CLIENTS = [
  { value: "sri-traders", label: "Sri Lakshmi Traders", hint: "3 agents" },
  { value: "vijaya-motors", label: "Vijaya Motors", hint: "1 agent" },
  { value: "lakshmi-textiles", label: "Lakshmi Textiles" },
  { value: "green-leaf", label: "Green Leaf Organics", hint: "Paused", disabled: true },
  { value: "anand-realty", label: "Anand Realty" },
];

const OUTCOMES = [
  { value: "booked", label: "Booked" },
  { value: "callback", label: "Call back" },
  { value: "not-interested", label: "Not interested" },
  { value: "no-answer", label: "No answer" },
];

const STATUSES = [
  { value: "new", label: "New" },
  { value: "contacted", label: "Contacted" },
  { value: "follow-up", label: "Follow-up" },
  { value: "won", label: "Won" },
  { value: "lost", label: "Lost" },
];

/** A save that takes a moment and fails on purpose when the name contains "fail". */
function useFakeSave(): [FeedbackStatus, (next: string) => void, string] {
  const [status, setStatus] = useState<FeedbackStatus>("idle");
  const [value, setValue] = useState("Reception desk");
  const save = (next: string) => {
    setStatus("pending");
    window.setTimeout(() => {
      if (next.toLowerCase().includes("fail")) setStatus("error");
      else {
        setValue(next);
        setStatus("success");
        window.setTimeout(() => setStatus("idle"), 2000);
      }
    }, 900);
  };
  return [status, save, value];
}

export function InputsSection() {
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const [toolbarQuery, setToolbarQuery] = useState("");
  const [client, setClient] = useState<string | null>(null);
  const [required, setRequired] = useState<string | null>("sri-traders");
  const [outcomes, setOutcomes] = useState<string[]>(["booked", "callback", "no-answer"]);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [statuses, setStatuses] = useState<string[]>(["won"]);
  const [choices, setChoices] = useState(["Interested", "Call back later"]);
  const [status, save, name] = useFakeSave();
  const [calls, setCalls] = useState<number | null>(3);
  const [cap, setCap] = useState<number | null>(600);
  const [topUp, setTopUp] = useState("");
  const [rateCap, setRateCap] = useState("125000.00");
  const [day, setDay] = useState<string | null>(addDays(todayIST(), 3));
  const [range, setRange] = useState<DateRange | null>({ start: addDays(todayIST(), -6), end: todayIST() });
  const [calendarDay, setCalendarDay] = useState<string>(todayIST());
  const [pause, setPause] = useState(700);
  const [hours, setHours] = useState<[number, number]>([9, 21]);
  const [band, setBand] = useState<string | null>("studio");
  const [period, setPeriod] = useState<Period>("month");
  const [view, setView] = useState("all");
  const [notices, setNotices] = useState(true);

  return (
    <KitSection
      id="inputs"
      title="Inputs"
      lead="Every field has a visible label above it, help under the label, and its own error under the control. Money is a decimal string; dates are India calendar days."
    >
      <KitGrid>
        <KitDemo label="SearchField · empty / typed / debounced" note={searched ? `Last search sent: “${searched}”` : "Type, wait or press Enter: the settled query is sent once."}>
          <SearchField label="Search leads" value={query} onValueChange={setQuery} onSearch={setSearched} placeholder="Name or number" />
        </KitDemo>
        <KitDemo label="SearchField · hidden label, disabled">
          <SearchField label="Search voices" hideLabel value="" onValueChange={() => {}} disabled placeholder="Search voices" />
        </KitDemo>
        <KitDemo label="ExpandingSearch · icon on a phone, field from sm" wide>
          <div className="flex items-center gap-2">
            <span className="text-body font-semibold text-ink">Campaigns</span>
            <div className="ml-auto flex min-w-0 items-center gap-2">
              <ExpandingSearch label="Search campaigns" value={toolbarQuery} onValueChange={setToolbarQuery} placeholder="Search campaigns" />
            </div>
          </div>
        </KitDemo>

        <KitDemo label="Combobox · clearable with an “all” row">
          <Combobox label="Client" allLabel="All clients" placeholder="Type a client's name" options={CLIENTS} value={client} onChange={setClient} />
        </KitDemo>
        <KitDemo label="Combobox · required, with an error">
          <Combobox label="Bill to" options={CLIENTS} value={required} onChange={setRequired} error={required ? null : "Choose the client this invoice is for."} />
        </KitDemo>
        <KitDemo label="Combobox · loading (server search) / disabled">
          <div className="space-y-3">
            <Combobox label="Agent" options={[]} value={null} onChange={() => {}} onQueryChange={() => {}} loading placeholder="Type an agent's name" />
            <Combobox label="Workspace" options={CLIENTS} value="sri-traders" onChange={() => {}} disabled />
          </div>
        </KitDemo>

        <KitDemo label="MultiSelect · some chosen / none">
          <div className="space-y-3">
            <MultiSelect label="Outcomes" emptyLabel="Any outcome" options={OUTCOMES} value={outcomes} onChange={setOutcomes} />
            <MultiSelect label="Clients" emptyLabel="All clients" options={CLIENTS} value={[]} onChange={() => {}} filterFrom={4} />
          </div>
        </KitDemo>
        <KitDemo label="ChipGroup · single with “All” / multiple">
          <div className="space-y-3">
            <ChipGroup mode="single" label="Filter calls by outcome" allLabel="All" chips={OUTCOMES} value={outcome} onChange={setOutcome} />
            <ChipGroup mode="multiple" label="Filter leads by status" chips={STATUSES} value={statuses} onChange={setStatuses} />
          </div>
        </KitDemo>

        <KitDemo label="TagInput · values, suggestions, duplicate refusal">
          <TagInput
            label="Choices for “Interest”"
            hint="Type a choice and press Enter."
            value={choices}
            onChange={setChoices}
            suggestions={["Interested", "Not interested", "Call back later", "Wrong number", "Already a customer"]}
          />
        </KitDemo>
        <KitDemo label="InlineEdit · idle → saving → saved / failed" note="Type a name containing “fail” to see the failure keep the text.">
          <InlineEdit label="Agent name" value={name} onSave={save} status={status} textClassName="text-title" />
        </KitDemo>

        <KitDemo label="NumberField · within limits / at the limit / unit">
          <div className="space-y-3">
            <NumberField label="Calls at the same time" hint="From 1 to 10." min={1} max={10} value={calls} onChange={setCalls} />
            <NumberField label="Longest call" unit="seconds" min={60} max={3600} step={30} value={cap} onChange={setCap} />
          </div>
        </KitDemo>
        <KitDemo label="NumberField · error / disabled">
          <div className="space-y-3">
            <NumberField label="Retries" min={0} max={3} value={null} onChange={() => {}} optional error="Enter how many times to try again, from 0 to 3." />
            <NumberField label="Concurrency" min={1} max={10} value={4} onChange={() => {}} disabled />
          </div>
        </KitDemo>

        <KitDemo label="MoneyInput · empty with quick amounts, min ₹500" note={`Value sent: ${topUp === "" ? "(empty)" : `"${topUp}"`}`}>
          <MoneyInput label="Add credit" paise={false} min="500.00" value={topUp} onChange={setTopUp} quickAmounts={["1000.00", "5000.00", "25000.00"]} />
        </KitDemo>
        <KitDemo label="MoneyInput · lakh grouping / error / disabled" note={`Value sent: "${rateCap}"`}>
          <div className="space-y-3">
            <MoneyInput label="Monthly spending cap" max="1000000.00" value={rateCap} onChange={setRateCap} />
            <MoneyInput label="Refund" value="" onChange={() => {}} error="Enter the amount to refund." />
            <MoneyInput label="Platform fee" value="2999.00" onChange={() => {}} disabled />
          </div>
        </KitDemo>

        <KitDemo label="DatePicker · chosen, past days disabled / clearable / error">
          <div className="space-y-3">
            <DatePicker label="Campaign starts" min={todayIST()} value={day} onChange={setDay} clearable />
            <DatePicker label="Letter issued on" max={todayIST()} value={null} onChange={() => {}} error="Choose the date on the letter." />
          </div>
        </KitDemo>
        <KitDemo label="DateRangePicker · presets and two taps">
          <DateRangePicker label="Calls between" max={todayIST()} value={range} onChange={setRange} />
        </KitDemo>
        <KitDemo label="Calendar · inline grid (today underlined, weekends allowed)">
          <div className="max-w-80">
            <Calendar label="Pick a day" selected={calendarDay} onSelect={setCalendarDay} />
          </div>
        </KitDemo>

        <KitDemo label="Slider · value as words, scale, preset marks">
          <Slider
            label="Pause before the agent answers"
            min={200}
            max={3000}
            step={50}
            value={pause}
            onChange={setPause}
            valueText={(v) => `${(v / 1000).toFixed(2)} s`}
            scale={["Quicker", "Slower"]}
            marks={[250, 500, 700]}
          />
        </KitDemo>
        <KitDemo label="RangeSlider · calling hours (IST)">
          <RangeSlider
            label="Calling hours"
            min={9}
            max={21}
            value={hours}
            onChange={setHours}
            valueText={(h) => `${String(h).padStart(2, "0")}:00`}
            scale={["09:00", "21:00"]}
          />
        </KitDemo>

        <KitDemo label="RadioGroup · with hints / error">
          <RadioGroup
            label="Voice"
            options={[
              { value: "clear", label: "Clear", hint: "Natural voices for most calls." },
              { value: "studio", label: "Studio", hint: "The richest voices, at a higher rate." },
              { value: "own", label: "Your own voice", hint: "Not set up yet.", disabled: true },
            ]}
            value={band}
            onChange={setBand}
          />
        </KitDemo>
        <KitDemo label="RadioGroup · inline, nothing chosen, error">
          <RadioGroup
            inline
            label="Who answers first?"
            options={[
              { value: "agent", label: "The agent" },
              { value: "caller", label: "The caller" },
            ]}
            value={null}
            onChange={() => {}}
            error="Choose who speaks first."
          />
        </KitDemo>

        <KitDemo label="PeriodToggle · the credit view">
          <PeriodToggle value={period} onChange={setPeriod} label="Credit shown for" />
        </KitDemo>
        <KitDemo label="SegmentedControl · with counts and a disabled option">
          <SegmentedControl
            label="Show"
            value={view}
            onValueChange={setView}
            options={[
              { value: "all", label: "All", count: "128" },
              { value: "review", label: "To review", count: "6" },
              { value: "done", label: "Reviewed" },
              { value: "held", label: "Held", disabled: true },
            ]}
          />
        </KitDemo>
        <KitDemo label="ToggleSwitch (ui.tsx) · on / disabled">
          <div className="space-y-3">
            <ToggleSwitch label="Tell callers the call is recorded" hint="Said at the start of every call." checked={notices} onChange={setNotices} />
            <ToggleSwitch label="Hang up when the caller is done" checked={false} disabled onChange={() => {}} />
          </div>
        </KitDemo>
      </KitGrid>
    </KitSection>
  );
}
