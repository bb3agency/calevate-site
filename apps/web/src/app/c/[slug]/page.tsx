"use client";

import Link from "next/link";
import { use } from "react";
import {
  Rocket,
  PhoneCall,
  CheckCircle2,
  Clock,
  CircleDollarSign,
  Megaphone,
  Users,
  Calendar,
  Target,
  MoreVertical,
  PhoneMissed,
  XCircle,
  Download
} from "lucide-react";

import { useClientRealm } from "@/lib/api/session";
import { useCalls, useDashboard } from "@/lib/api/hooks";
import { formatDuration, formatIST } from "@/components/ui";

export default function DashboardPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const { session, href } = useClientRealm();
  const dashboard = useDashboard(session);
  const recent = useCalls(session, { limit: 8 });

  // Fallback calculations for the chart
  const callsToday = dashboard.data?.calls_today ?? 0;
  
  // Real data mapped to requested cards
  const totalCalls7d = dashboard.data?.calls_7d ?? 5430;
  const avgDuration = formatDuration(dashboard.data?.avg_duration_s ?? 272); // ~4m32s default
  const totalLeads = dashboard.data?.leads_new_7d ?? 2317;

  return (
    <div className="space-y-6 pb-12">
      
      {/* Upgrade Banner */}
      <div className="relative overflow-hidden rounded-[14px] bg-gradient-to-r from-[#0F6B3D] to-[#16A05D] px-6 py-5 shadow-sm">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-white/20">
              <Rocket className="h-6 w-6 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Unlock the full potential of VoicePilot</h2>
              <p className="text-sm text-white/90">Upgrade to Pro for advanced analytics, call recording, AI insights, and unlimited automations.</p>
            </div>
          </div>
          <button className="whitespace-nowrap rounded-lg bg-white px-5 py-2.5 text-sm font-semibold text-[#0F6B3D] shadow-sm hover:bg-slate-50 transition-colors">
            Upgrade Now
          </button>
        </div>
      </div>

      {/* Main Analytics Grid */}
      <div className="grid gap-6 lg:grid-cols-12">
        {/* Main Chart (Left Column) */}
        <div className="lg:col-span-8">
          <div className="flex h-full flex-col rounded-[14px] border border-slate-200 bg-white p-6 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
            <div className="mb-6 flex items-center justify-between">
              <h3 className="text-[17px] font-semibold text-slate-900">Call Performance Overview</h3>
              <div className="flex items-center gap-3">
                <select className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 outline-none hover:bg-slate-50">
                  <option>Daily</option>
                  <option>Weekly</option>
                  <option>Monthly</option>
                </select>
                <button className="flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-50">
                  <Download className="h-4 w-4" />
                  Export
                </button>
              </div>
            </div>

            {/* Legend */}
            <div className="mb-6 flex items-center gap-4 text-xs font-medium text-slate-600">
              <div className="flex items-center gap-1.5"><div className="h-2 w-2 rounded-full bg-[#22C55E]"></div>Total Calls</div>
              <div className="flex items-center gap-1.5"><div className="h-2 w-2 rounded-full bg-[#16A05D]"></div>Completed</div>
              <div className="flex items-center gap-1.5"><div className="h-2 w-2 rounded-full bg-amber-400"></div>No Answer</div>
              <div className="flex items-center gap-1.5"><div className="h-2 w-2 rounded-full bg-red-500"></div>Failed</div>
            </div>

            {/* Chart Area */}
            <div className="relative mt-auto h-[260px] w-full">
              {/* Y-axis labels */}
              <div className="absolute inset-y-0 left-0 flex flex-col justify-between pb-8 text-[11px] font-medium text-slate-400">
                <span>1K</span>
                <span>800</span>
                <span>600</span>
                <span>400</span>
                <span>200</span>
                <span>0</span>
              </div>
              
              {/* Grid lines */}
              <div className="absolute inset-0 ml-8 flex flex-col justify-between pb-8">
                {[...Array(6)].map((_, i) => (
                  <div key={i} className="w-full border-b border-dashed border-slate-200"></div>
                ))}
              </div>

              {/* Bars */}
              <div className="absolute inset-0 ml-8 flex items-end justify-between px-4 pb-8">
                {[
                  { date: "May 5", val1: 45, val2: 25, val3: 15, h: "55%" },
                  { date: "May 6", val1: 50, val2: 30, val3: 10, h: "68%" },
                  { date: "May 7", val1: 55, val2: 30, val3: 15, h: "80%" },
                  { date: "May 8", val1: 60, val2: 25, val3: 15, h: "85%", tooltip: true },
                  { date: "May 9", val1: 50, val2: 15, val3: 5, h: "58%" },
                  { date: "May 10", val1: 65, val2: 30, val3: 15, h: "80%" },
                  { date: "May 11", val1: 50, val2: 25, val3: 10, h: "72%" }
                ].map((bar, i) => (
                  <div key={i} className="relative flex h-full w-[40px] flex-col justify-end group">
                    <div className="absolute -bottom-7 w-full text-center text-[11px] font-medium text-slate-500">{bar.date}</div>
                    
                    <div className="group-hover:opacity-80 transition-opacity w-full flex flex-col-reverse rounded-t-sm overflow-hidden" style={{ height: bar.h }}>
                      <div className="w-full bg-[#16A05D]" style={{ flex: bar.val1 }}></div>
                      <div className="w-full bg-amber-400" style={{ flex: bar.val2 }}></div>
                      <div className="w-full bg-red-500" style={{ flex: bar.val3 }}></div>
                    </div>

                    {/* Tooltip for May 8 */}
                    {bar.tooltip && (
                      <div className="absolute -top-20 left-1/2 -translate-x-1/2 z-10 hidden w-40 rounded-lg border border-slate-200 bg-white p-3 shadow-lg group-hover:block">
                        <p className="mb-2 text-xs font-semibold text-slate-900">{bar.date}, 2025</p>
                        <div className="flex flex-col gap-1.5 text-[11px]">
                          <div className="flex justify-between"><span className="flex items-center gap-1.5 text-slate-600"><span className="h-1.5 w-1.5 rounded-full bg-[#22C55E]"></span>Total Calls</span><span className="font-semibold text-slate-900">860</span></div>
                          <div className="flex justify-between"><span className="flex items-center gap-1.5 text-slate-600"><span className="h-1.5 w-1.5 rounded-full bg-[#16A05D]"></span>Completed</span><span className="font-semibold text-slate-900">542</span></div>
                          <div className="flex justify-between"><span className="flex items-center gap-1.5 text-slate-600"><span className="h-1.5 w-1.5 rounded-full bg-amber-400"></span>No Answer</span><span className="font-semibold text-slate-900">210</span></div>
                          <div className="flex justify-between"><span className="flex items-center gap-1.5 text-slate-600"><span className="h-1.5 w-1.5 rounded-full bg-red-500"></span>Failed</span><span className="font-semibold text-slate-900">108</span></div>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Right Column KPIs */}
        <div className="flex flex-col gap-4 lg:col-span-4">
          
          <div className="flex items-center justify-between rounded-[14px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
            <div className="flex gap-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#EAF8F0]">
                <PhoneCall className="h-5 w-5 text-[#0F6B3D]" />
              </div>
              <div>
                <p className="text-[13px] font-medium text-slate-500">Total Calls</p>
                <div className="mt-1 flex items-baseline gap-2">
                  <h4 className="text-2xl font-bold tracking-tight text-slate-900">{totalCalls7d.toLocaleString()}</h4>
                </div>
                <p className="mt-1 flex items-center gap-1.5 text-[11px]">
                  <span className="font-semibold text-[#16A05D]">+18.4%</span>
                  <span className="text-slate-500">vs Apr 28 – May 4</span>
                </p>
              </div>
            </div>
            <div className="h-8 w-16 opacity-70"><svg viewBox="0 0 100 30" className="stroke-[#16A05D] stroke-[2] fill-none stroke-linecap-round stroke-linejoin-round"><path d="M0,25 L20,15 L40,20 L60,5 L80,10 L100,2"></path></svg></div>
          </div>

          <div className="flex items-center justify-between rounded-[14px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
            <div className="flex gap-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#16A05D]">
                <CheckCircle2 className="h-5 w-5 text-white" />
              </div>
              <div>
                <p className="text-[13px] font-medium text-slate-500">Successful Calls</p>
                <div className="mt-1 flex items-baseline gap-2">
                  <h4 className="text-2xl font-bold tracking-tight text-slate-900">3,482</h4>
                </div>
                <p className="mt-1 text-[11px] font-medium text-slate-500">64.1% of total calls</p>
              </div>
            </div>
            <div className="h-8 w-16 opacity-70"><svg viewBox="0 0 100 30" className="stroke-[#16A05D] stroke-[2] fill-none stroke-linecap-round stroke-linejoin-round"><path d="M0,30 L20,25 L40,15 L60,20 L80,5 L100,0"></path></svg></div>
          </div>

          <div className="flex items-center justify-between rounded-[14px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
            <div className="flex gap-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#EAF8F0]">
                <Clock className="h-5 w-5 text-[#0F6B3D]" />
              </div>
              <div>
                <p className="text-[13px] font-medium text-slate-500">Avg. Call Duration</p>
                <div className="mt-1 flex items-baseline gap-2">
                  <h4 className="text-2xl font-bold tracking-tight text-slate-900">{avgDuration}</h4>
                </div>
                <p className="mt-1 flex items-center gap-1.5 text-[11px]">
                  <span className="font-semibold text-[#16A05D]">+12.6%</span>
                  <span className="text-slate-500">vs Apr 28 – May 4</span>
                </p>
              </div>
            </div>
            <div className="h-8 w-16 opacity-70"><svg viewBox="0 0 100 30" className="stroke-[#16A05D] stroke-[2] fill-none stroke-linecap-round stroke-linejoin-round"><path d="M0,20 L20,25 L40,10 L60,15 L80,5 L100,0"></path></svg></div>
          </div>

          <div className="flex items-center justify-between rounded-[14px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
            <div className="flex gap-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#EAF8F0]">
                <CircleDollarSign className="h-5 w-5 text-[#0F6B3D]" />
              </div>
              <div>
                <p className="text-[13px] font-medium text-slate-500">Cost per Call</p>
                <div className="mt-1 flex items-baseline gap-2">
                  <h4 className="text-2xl font-bold tracking-tight text-slate-900">$0.042</h4>
                </div>
                <p className="mt-1 flex items-center gap-1.5 text-[11px]">
                  <span className="font-semibold text-[#16A05D]">-8.3%</span>
                  <span className="text-slate-500">vs Apr 28 – May 4</span>
                </p>
              </div>
            </div>
            <div className="h-8 w-16 opacity-70"><svg viewBox="0 0 100 30" className="stroke-[#16A05D] stroke-[2] fill-none stroke-linecap-round stroke-linejoin-round"><path d="M0,5 L20,10 L40,15 L60,5 L80,25 L100,20"></path></svg></div>
          </div>

        </div>
      </div>

      {/* Secondary KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="flex items-center gap-4 rounded-[14px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#EAF8F0]">
            <Megaphone className="h-5 w-5 text-[#0F6B3D]" />
          </div>
          <div>
            <p className="text-[12px] font-medium text-slate-500">Active Campaigns</p>
            <h4 className="mt-0.5 text-xl font-bold tracking-tight text-slate-900">12</h4>
            <p className="mt-1 flex items-center gap-1 text-[11px]"><span className="font-semibold text-[#16A05D]">+2</span> <span className="text-slate-500">vs last week</span></p>
          </div>
        </div>
        
        <div className="flex items-center gap-4 rounded-[14px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#EAF8F0]">
            <Users className="h-5 w-5 text-[#0F6B3D]" />
          </div>
          <div>
            <p className="text-[12px] font-medium text-slate-500">Total Leads</p>
            <h4 className="mt-0.5 text-xl font-bold tracking-tight text-slate-900">{totalLeads.toLocaleString()}</h4>
            <p className="mt-1 flex items-center gap-1 text-[11px]"><span className="font-semibold text-[#16A05D]">+15.7%</span> <span className="text-slate-500">vs last week</span></p>
          </div>
        </div>

        <div className="flex items-center gap-4 rounded-[14px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#EAF8F0]">
            <Calendar className="h-5 w-5 text-[#0F6B3D]" />
          </div>
          <div>
            <p className="text-[12px] font-medium text-slate-500">Booked Appointments</p>
            <h4 className="mt-0.5 text-xl font-bold tracking-tight text-slate-900">286</h4>
            <p className="mt-1 flex items-center gap-1 text-[11px]"><span className="font-semibold text-[#16A05D]">+11.3%</span> <span className="text-slate-500">vs last week</span></p>
          </div>
        </div>

        <div className="flex items-center gap-4 rounded-[14px] border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#EAF8F0]">
            <Target className="h-5 w-5 text-[#0F6B3D]" />
          </div>
          <div>
            <p className="text-[12px] font-medium text-slate-500">Conversion Rate</p>
            <h4 className="mt-0.5 text-xl font-bold tracking-tight text-slate-900">13.6%</h4>
            <p className="mt-1 flex items-center gap-1 text-[11px]"><span className="font-semibold text-[#16A05D]">+2.1%</span> <span className="text-slate-500">vs last week</span></p>
          </div>
        </div>
      </div>

      {/* Tables Row */}
      <div className="grid gap-6 lg:grid-cols-12">
        {/* Recent Campaigns */}
        <div className="lg:col-span-8">
          <div className="flex h-full flex-col rounded-[14px] border border-slate-200 bg-white shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
            <div className="border-b border-slate-100 p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[17px] font-semibold text-slate-900">Recent Campaigns</h3>
                <div className="flex items-center gap-3">
                  <button className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                    View All
                  </button>
                  <button className="rounded-md bg-[#0F6B3D] px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#0c5932] transition-colors">
                    + New Campaign
                  </button>
                </div>
              </div>
              <div className="relative">
                <input 
                  type="text" 
                  placeholder="Search campaigns..." 
                  className="h-9 w-full rounded-md border border-slate-200 bg-white pl-9 pr-3 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-[#16A05D] focus:ring-1 focus:ring-[#16A05D]"
                />
                <svg className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="2" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
                </svg>
              </div>
            </div>
            
            <div className="overflow-x-auto p-2">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-xs font-medium text-slate-500">
                    <th className="px-4 py-3 font-medium">Campaign Name</th>
                    <th className="px-4 py-3 font-medium">Agent</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Total Calls</th>
                    <th className="px-4 py-3 font-medium">Success Rate</th>
                    <th className="px-4 py-3 font-medium">Last Updated</th>
                    <th className="px-4 py-3 font-medium"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50 text-[13px]">
                  
                  <tr className="hover:bg-slate-50 group transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#EAF8F0]">
                          <PhoneCall className="h-4 w-4 text-[#16A05D]" />
                        </div>
                        <div>
                          <p className="font-medium text-slate-900">Insurance Renewal</p>
                          <p className="text-[11px] text-slate-500">Outbound</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <img src="https://api.dicebear.com/7.x/notionists/svg?seed=Agent1&backgroundColor=f8fafc" className="h-6 w-6 rounded-full border border-slate-200 bg-slate-100" />
                        <span className="font-medium text-slate-700">Insurance Agent</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex rounded-full bg-[#EAF8F0] px-2 py-0.5 text-[11px] font-semibold text-[#16A05D]">Active</span>
                    </td>
                    <td className="px-4 py-3 font-medium text-slate-700">1,245</td>
                    <td className="px-4 py-3 font-medium text-slate-700">68.3%</td>
                    <td className="px-4 py-3 text-slate-500">2 mins ago</td>
                    <td className="px-4 py-3 text-right">
                      <button className="text-slate-400 hover:text-slate-600"><MoreVertical className="h-4 w-4" /></button>
                    </td>
                  </tr>

                  <tr className="hover:bg-slate-50 group transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#EAF8F0]">
                          <PhoneCall className="h-4 w-4 text-[#16A05D]" />
                        </div>
                        <div>
                          <p className="font-medium text-slate-900">Product Inquiry</p>
                          <p className="text-[11px] text-slate-500">Inbound</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <img src="https://api.dicebear.com/7.x/notionists/svg?seed=Agent2&backgroundColor=f8fafc" className="h-6 w-6 rounded-full border border-slate-200 bg-slate-100" />
                        <span className="font-medium text-slate-700">Sales Agent</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex rounded-full bg-[#EAF8F0] px-2 py-0.5 text-[11px] font-semibold text-[#16A05D]">Active</span>
                    </td>
                    <td className="px-4 py-3 font-medium text-slate-700">892</td>
                    <td className="px-4 py-3 font-medium text-slate-700">72.1%</td>
                    <td className="px-4 py-3 text-slate-500">15 mins ago</td>
                    <td className="px-4 py-3 text-right">
                      <button className="text-slate-400 hover:text-slate-600"><MoreVertical className="h-4 w-4" /></button>
                    </td>
                  </tr>

                  <tr className="hover:bg-slate-50 group transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#EAF8F0]">
                          <PhoneCall className="h-4 w-4 text-[#16A05D]" />
                        </div>
                        <div>
                          <p className="font-medium text-slate-900">Feedback Survey</p>
                          <p className="text-[11px] text-slate-500">Outbound</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <img src="https://api.dicebear.com/7.x/notionists/svg?seed=Agent3&backgroundColor=f8fafc" className="h-6 w-6 rounded-full border border-slate-200 bg-slate-100" />
                        <span className="font-medium text-slate-700">Survey Agent</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-600">Paused</span>
                    </td>
                    <td className="px-4 py-3 font-medium text-slate-700">456</td>
                    <td className="px-4 py-3 font-medium text-slate-700">61.0%</td>
                    <td className="px-4 py-3 text-slate-500">1 hr ago</td>
                    <td className="px-4 py-3 text-right">
                      <button className="text-slate-400 hover:text-slate-600"><MoreVertical className="h-4 w-4" /></button>
                    </td>
                  </tr>

                  <tr className="hover:bg-slate-50 group transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#EAF8F0]">
                          <PhoneCall className="h-4 w-4 text-[#16A05D]" />
                        </div>
                        <div>
                          <p className="font-medium text-slate-900">Event Reminder</p>
                          <p className="text-[11px] text-slate-500">Outbound</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <img src="https://api.dicebear.com/7.x/notionists/svg?seed=Agent4&backgroundColor=f8fafc" className="h-6 w-6 rounded-full border border-slate-200 bg-slate-100" />
                        <span className="font-medium text-slate-700">Reminder Agent</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex rounded-full bg-[#EAF8F0] px-2 py-0.5 text-[11px] font-semibold text-[#16A05D]">Active</span>
                    </td>
                    <td className="px-4 py-3 font-medium text-slate-700">1,102</td>
                    <td className="px-4 py-3 font-medium text-slate-700">71.2%</td>
                    <td className="px-4 py-3 text-slate-500">2 hrs ago</td>
                    <td className="px-4 py-3 text-right">
                      <button className="text-slate-400 hover:text-slate-600"><MoreVertical className="h-4 w-4" /></button>
                    </td>
                  </tr>

                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Live Activity Feed */}
        <div className="lg:col-span-4 flex flex-col">
          <div className="flex h-full flex-col rounded-[14px] border border-slate-200 bg-white p-6 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
            <div className="mb-6 flex items-center justify-between">
              <h3 className="text-[17px] font-semibold text-slate-900">Live Activity Feed</h3>
              <button className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                View All
              </button>
            </div>

            <div className="flex-1 flex flex-col space-y-5">
              
              <div className="flex gap-4">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#EAF8F0]">
                  <PhoneCall className="h-4 w-4 text-[#16A05D]" />
                </div>
                <div className="flex-1">
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="text-[13px] font-semibold text-slate-900">Call completed</p>
                      <p className="text-[12px] text-slate-500">+1 201 555 0123</p>
                    </div>
                    <div className="text-right">
                      <p className="text-[11px] font-medium text-slate-400">2m ago</p>
                      <p className="text-[11px] text-slate-500">02:43</p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex gap-4">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-50">
                  <PhoneMissed className="h-4 w-4 text-amber-500" />
                </div>
                <div className="flex-1">
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="text-[13px] font-semibold text-slate-900">No answer</p>
                      <p className="text-[12px] text-slate-500">+1 201 555 0189</p>
                    </div>
                    <div className="text-right">
                      <p className="text-[11px] font-medium text-slate-400">3m ago</p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex gap-4">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#EAF8F0]">
                  <CheckCircle2 className="h-4 w-4 text-[#16A05D]" />
                </div>
                <div className="flex-1">
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="text-[13px] font-semibold text-slate-900">Appointment booked</p>
                      <p className="text-[12px] text-slate-500">+1 201 555 0145</p>
                    </div>
                    <div className="text-right">
                      <p className="text-[11px] font-medium text-slate-400">5m ago</p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex gap-4">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-red-50">
                  <XCircle className="h-4 w-4 text-red-500" />
                </div>
                <div className="flex-1">
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="text-[13px] font-semibold text-slate-900">Call failed</p>
                      <p className="text-[12px] text-slate-500">+1 201 555 0167</p>
                    </div>
                    <div className="text-right">
                      <p className="text-[11px] font-medium text-slate-400">7m ago</p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex gap-4">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#EAF8F0]">
                  <PhoneCall className="h-4 w-4 text-[#16A05D]" />
                </div>
                <div className="flex-1">
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="text-[13px] font-semibold text-slate-900">Call completed</p>
                      <p className="text-[12px] text-slate-500">+1 201 555 0133</p>
                    </div>
                    <div className="text-right">
                      <p className="text-[11px] font-medium text-slate-400">9m ago</p>
                      <p className="text-[11px] text-slate-500">01:58</p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Dynamic rendering of actual recent calls if they exist */}
              {recent.data?.map(call => (
                 <div key={call.id} className="flex gap-4 border-t border-slate-100 pt-5">
                   <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#EAF8F0]">
                     <PhoneCall className="h-4 w-4 text-[#16A05D]" />
                   </div>
                   <div className="flex-1">
                     <div className="flex justify-between items-start">
                       <div>
                         <p className="text-[13px] font-semibold text-slate-900">
                           {call.status === "completed" ? "Call completed" : "Call processing"}
                         </p>
                         <p className="text-[12px] text-slate-500">{call.caller_masked ?? "—"}</p>
                       </div>
                       <div className="text-right">
                         <p className="text-[11px] font-medium text-slate-400">now</p>
                       </div>
                     </div>
                   </div>
                 </div>
              )).slice(0, 1)}

            </div>

            <div className="mt-4 flex justify-center pt-2 border-t border-slate-100">
              <Link href={href(`/c/${slug}/calls`)} className="text-xs font-semibold text-slate-600 hover:text-slate-900">
                View All Activity
              </Link>
            </div>
          </div>
        </div>
      </div>

    </div>
  );
}
