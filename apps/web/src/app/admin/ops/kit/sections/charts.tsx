"use client";

import { useEffect, useState } from "react";
import { ActivityHeatmap, type HeatmapCell } from "@/components/arc/activity-heatmap";
import { BarChart } from "@/components/arc/bar-chart";
import { BrushChart } from "@/components/arc/brush-chart";
import { Countdown } from "@/components/arc/countdown";
import { DonutChart } from "@/components/arc/donut-chart";
import { Gauge } from "@/components/arc/gauge";
import { LineChart } from "@/components/arc/line-chart";
import { Ridgeline } from "@/components/arc/ridgeline";
import { Sparkline } from "@/components/arc/sparkline";
import { StatsBand } from "@/components/arc/stats-band";
import { Timeline, TimelineItem } from "@/components/arc/timeline";
import { UsageMeter } from "@/components/arc/usage-meter";
import { Metric, MetricRow } from "@/components/console/metric";
import { formatCount, formatINRExact } from "@/components/ui";
import { CircleDot, PhoneCall, StickyNote } from "lucide-react";

import { KitDemo, KitGrid, KitSection } from "../kitLayout";

const WEEK = ["Mon 20", "Tue 21", "Wed 22", "Thu 23", "Fri 24", "Sat 25", "Sun 26"];
const ANSWERED = [42, 51, 38, 64, 58, 22, 17];
const MISSED = [4, 6, 3, 9, 5, 2, 1];

/** A believable week: busy late mornings and early evenings, quiet Sunday mornings. */
const HEAT: HeatmapCell[] = Array.from({ length: 7 }, (_, weekday) =>
  Array.from({ length: 24 }, (_, hour) => {
    const day = weekday === 6 ? 0.4 : weekday === 5 ? 0.7 : 1;
    const shape = hour < 8 || hour > 21 ? 0 : hour >= 10 && hour <= 12 ? 9 : hour >= 17 && hour <= 19 ? 7 : 3;
    return { weekday, hour, count: Math.round(shape * day + ((weekday * 7 + hour * 3) % 4)) };
  }),
).flat();

/** Ninety days of leads captured, with a campaign bump in the middle. */
const DAYS = Array.from({ length: 90 }, (_, i) => {
  const at = new Date(Date.UTC(2026, 6, 27) + i * 86_400_000);
  return `${at.getUTCDate()} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][at.getUTCMonth()]}`;
});
const LEADS = DAYS.map((_, i) => Math.round(8 + 6 * Math.sin(i / 5) + (i > 40 && i < 55 ? 18 : 0) + (i % 7 === 6 ? -5 : 0)));

const DURATIONS = (seed: number, centre: number) =>
  Array.from({ length: 80 }, (_, i) => Math.max(15, Math.round(centre + Math.sin(i * seed) * centre * 0.6 + ((i * 37) % 50) - 25)));

const SPEND = ["412.50", "530.00", "388.25", "610.75", "575.00", "205.50", "160.00"];

export function ChartsSection() {
  // Clock-dependent specimens render after mount, so the server render cannot disagree.
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => setNow(Date.now()), []);
  return (
    <KitSection
      id="charts"
      title="Charts and figures"
      lead="Every chart renders its data twice: as marks for the eye and as a table for a screen reader (Show as table). Colours follow the series' order, never its rank."
    >
      <KitDemo label="StatsBand · figures with change and trend" wide>
        <StatsBand
          label="This week at a glance"
          items={[
            { label: "Calls answered", value: formatCount(292), delta: { text: "+18%", direction: "up", good: true, context: "vs last week" }, trend: ANSWERED },
            { label: "Missed", value: formatCount(30), delta: { text: "−4", direction: "down", good: true, context: "vs last week" }, trend: MISSED },
            { label: "Leads captured", value: formatCount(1_20_450), hint: "All time" },
            { label: "Credit used", value: formatINRExact("2882.00"), delta: { text: "+₹310.00", direction: "up", good: false }, trend: SPEND.map(Number) },
          ]}
        />
      </KitDemo>
      <KitGrid>
        <KitDemo label="Metric · unknown value" note="A figure we could not read is a dash with its reason, never a zero.">
          <MetricRow>
            <Metric label="Answer rate" value="—" hint="Could not load this week" />
            <Metric label="Credit left" value={formatINRExact("84.50")} tone="warn" hint="Calls pause at ₹0.00" />
          </MetricRow>
        </KitDemo>
        <KitDemo label="Sparkline · brand and neutral">
          <div className="flex items-center gap-6">
            <Sparkline values={ANSWERED} label="Calls answered, last 7 days" area />
            <Sparkline values={MISSED} label="Missed calls, last 7 days" tone="neutral" />
            <Sparkline values={[]} label="Leads, last 7 days" />
          </div>
        </KitDemo>
        <KitDemo label="LineChart · two series">
          <LineChart
            title="Calls per day"
            description="Last 7 days, IST"
            labelColumn="Day"
            labels={WEEK}
            series={[
              { label: "Answered", values: ANSWERED },
              { label: "Missed", values: MISSED },
            ]}
          />
        </KitDemo>
        <KitDemo label="LineChart · single series with a gap">
          <LineChart
            title="Average call length"
            description="Seconds, a gap where no calls ran"
            labelColumn="Day"
            labels={WEEK}
            area
            series={[{ label: "Seconds", values: [94, 102, null, 88, 120, 97, 110] }]}
          />
        </KitDemo>
        <KitDemo label="BarChart · vertical, stacked">
          <BarChart
            title="Outcomes per day"
            labelColumn="Day"
            categories={WEEK}
            stacked
            series={[
              { label: "Lead captured", values: [18, 22, 15, 30, 26, 9, 7] },
              { label: "Answered only", values: [24, 29, 23, 34, 32, 13, 10] },
              { label: "Missed", values: MISSED },
            ]}
          />
        </KitDemo>
        <KitDemo label="BarChart · horizontal with values (money)">
          <BarChart
            title="Credit used by agent"
            description="This month"
            orientation="horizontal"
            showValues
            labelColumn="Agent"
            categories={["Reception (Telugu)", "Follow-up calls", "అపాయింట్‌మెంట్ రిమైండర్"]}
            series={[{ label: "Spent", values: [1840.5, 742, 299.5], display: [formatINRExact("1840.50"), formatINRExact("742.00"), formatINRExact("299.50")] }]}
          />
        </KitDemo>
        <KitDemo label="DonutChart · outcomes, folded past six">
          <DonutChart
            title="How calls ended"
            centerLabel="calls"
            segments={[
              { label: "Lead captured", value: 127 },
              { label: "Question answered", value: 98 },
              { label: "Transferred", value: 31 },
              { label: "Caller hung up", value: 22 },
              { label: "Wrong number", value: 9 },
              { label: "Voicemail", value: 4 },
              { label: "Other", value: 1 },
            ]}
          />
        </KitDemo>
        <KitDemo label="ActivityHeatmap · calls by IST weekday and hour" wide>
          <ActivityHeatmap title="When callers ring" description="Last 4 weeks, IST" cells={HEAT} />
        </KitDemo>
        <KitDemo label="BrushChart · 90 days of leads" wide note="Drag the window or its edges; with a keyboard, focus an edge and use the arrow keys.">
          <BrushChart title="Leads captured per day" seriesLabel="Leads" labels={DAYS} values={LEADS} />
        </KitDemo>
        <KitDemo label="Ridgeline · call length by agent" wide>
          <Ridgeline
            title="How long calls run"
            description="This month, minutes:seconds"
            labelColumn="Agent"
            series={[
              { label: "Reception", values: DURATIONS(0.7, 110) },
              { label: "Follow-up calls", values: DURATIONS(1.3, 210) },
              { label: "Reminders", values: DURATIONS(2.1, 55) },
            ]}
          />
        </KitDemo>
        <KitDemo label="Gauge · readiness with what to fix">
          <Gauge
            value={64}
            label="Readiness"
            fixes={[
              { id: "q", label: "Answer the 3 questions callers asked this week", detail: "Missed questions lower the score most", points: 12, href: "#charts" },
              { id: "t", label: "Pass two more practice tests", points: 8, href: "#charts" },
              { id: "n", label: "Turn on the recording notice", points: 6, href: "#charts" },
            ]}
          />
        </KitDemo>
        <KitDemo label="Gauge · ready, and not yet scored">
          <div className="space-y-4">
            <Gauge value={91} label="Readiness" fixes={[]} />
            <Gauge value={null} label="Readiness" pendingText="Run a practice test to get a score" />
          </div>
        </KitDemo>
        <KitDemo label="UsageMeter · trial minutes, cap and over">
          <div className="space-y-5">
            <UsageMeter label="Free minutes" used={42} limit={60} usedText="42" limitText="60 minutes" hint="Test calls stop at 60 minutes." />
            <UsageMeter label="Spending cap" used={4710} limit={5000} usedText={formatINRExact("4710.00")} limitText={formatINRExact("5000.00")} hint="Calls pause at the cap." />
            <UsageMeter label="Included minutes" used={1150} limit={1000} usedText="1,150" limitText="1,000" overTone="warn" caption="150 extra minutes, billed at your rate" />
            <UsageMeter
              label="Minutes by agent"
              used={640}
              limit={1000}
              usedText="640"
              limitText="1,000"
              segments={[
                { label: "Reception", value: 410 },
                { label: "Follow-up", value: 180 },
                { label: "Reminders", value: 50 },
              ]}
            />
            <UsageMeter label="Room left in the instructions" variant="inline" used={7400} limit={8000} usedText="7,400" caption="600 letters left" />
          </div>
        </KitDemo>
        <KitDemo label="Timeline · a lead's history">
          <Timeline label="Lead history">
            <TimelineItem icon={PhoneCall} title="Called back, interested in a Saturday slot" meta="24 Oct, 10:42 am · Calevate" />
            <TimelineItem icon={CircleDot} markerClassName="bg-brand-soft text-brand-strong" title="Status: Follow-up" detail="Moved from New" meta="23 Oct, 6:05 pm · Priya" />
            <TimelineItem icon={StickyNote} markerClassName="bg-warn-soft text-warn" title="Note added" detail="Prefers Telugu, call after 5 pm" meta="23 Oct, 6:04 pm · Priya" />
          </Timeline>
        </KitDemo>
        <KitDemo label="Countdown · server-clock corrected">
          {now === null ? null : (
            <div className="space-y-2 text-body">
              <Countdown
                target={new Date(now + 2 * 3600_000 + 14 * 60_000).toISOString()}
                serverNow={new Date(now).toISOString()}
                label="Calling opens in"
                showTarget
              />
              <Countdown target={new Date(now - 1000).toISOString()} label="Trial ends in" doneText="Trial has ended" />
            </div>
          )}
        </KitDemo>
        <KitDemo label="States · loading, empty, error">
          <div className="space-y-6">
            <LineChart title="Calls per day" labels={[]} series={[]} loading height={120} />
            <BarChart title="Calls per day" categories={[]} series={[]} empty="No calls this week yet." height={120} />
            <DonutChart title="How calls ended" segments={[]} error="We could not load your calls. Try again in a moment." />
          </div>
        </KitDemo>
      </KitGrid>
    </KitSection>
  );
}
