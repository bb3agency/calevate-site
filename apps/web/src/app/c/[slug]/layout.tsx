"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { use, useState } from "react";
import {
  LayoutDashboard,
  Megaphone,
  Bot,
  PhoneCall,
  Users,
  BookOpen,
  BarChart3,
  Activity,
  Bell,
  Blocks,
  GitMerge,
  FileText,
  Code2,
  ChevronDown,
  MessageSquare,
  Mic,
  Calendar,
  Target,
  PanelLeftClose,
  PanelLeftOpen,
  PhoneOff,
  ShieldCheck,
  Menu,
  X
} from "lucide-react";

import { Providers } from "@/app/providers";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { ClientRealmProvider, useClientRealm } from "@/lib/api/session";

function Sidebar({ slug, isMobileOpen, onClose }: { slug: string; isMobileOpen: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const { href } = useClientRealm();
  const [isCollapsed, setIsCollapsed] = useState(false);
  
  const mainNav = [
    { href: `/c/${slug}`, label: "Dashboard", icon: LayoutDashboard },
    { href: `/c/${slug}/campaigns`, label: "Campaigns", icon: Megaphone },
    { href: `/c/${slug}/agents`, label: "Voice Agents", icon: Bot },
    { href: `/c/${slug}/calls`, label: "Call Logs", icon: PhoneCall },
    { href: `/c/${slug}/leads`, label: "Leads", icon: Users },
    { href: `/c/${slug}/knowledge`, label: "Knowledge Base", icon: BookOpen },
    { href: `/c/${slug}/performance`, label: "Performance", icon: BarChart3 },
  ];

  const operationsNav = [
    { href: `/c/${slug}/attention`, label: "Needs attention", icon: Target },
    { href: `/c/${slug}/campaign-review`, label: "Campaign review", icon: FileText },
  ];

  const complianceNav = [
    { href: `/c/${slug}/do-not-call`, label: "Do not call", icon: PhoneOff },
    { href: `/c/${slug}/messaging-consent`, label: "Messaging consent", icon: MessageSquare },
    { href: `/c/${slug}/lead-sources`, label: "Lead sources", icon: GitMerge },
  ];

  const settingsNav = [
    { href: `/c/${slug}/integrations`, label: "Integrations", icon: Blocks },
    { href: `/c/${slug}/usage`, label: "Usage", icon: Activity },
    { href: `/c/${slug}/verification`, label: "Verification", icon: ShieldCheck },
  ];

  const renderItem = (item: any, isSubItem = false) => {
    const active = pathname === item.href;
    const isExpanded = item.items && item.items.some((sub: any) => pathname.startsWith(sub.href));

    return (
      <div key={item.label} className="mb-1">
        {item.href ? (
          <Link
            href={href(item.href)}
            title={isCollapsed ? item.label : undefined}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              active
                ? "bg-[#EAF8F0] text-[#0F6B3D] dark:bg-[#0F6B3D]/20 dark:text-[#22C55E]"
                : "text-slate-600 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-800"
            } ${isSubItem ? (isCollapsed ? "pl-3 text-[13px] py-1.5 justify-center" : "pl-9 text-[13px] py-1.5") : (isCollapsed ? "justify-center" : "")}`}
          >
            {item.icon && <item.icon className={`h-4 w-4 shrink-0 ${active ? "text-[#16A05D]" : "text-slate-400"}`} />}
            {!isCollapsed && <span className="flex-1 truncate">{item.label}</span>}
            {!isCollapsed && item.badge && (
              <span className="rounded bg-[#22C55E] px-1.5 py-0.5 text-[10px] font-bold text-white shrink-0">
                {item.badge}
              </span>
            )}
            {!isCollapsed && item.alertCount && (
              <span className="flex h-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-[11px] font-bold text-white shrink-0">
                {item.alertCount < 10 ? `0${item.alertCount}` : item.alertCount}
              </span>
            )}
          </Link>
        ) : (
          <div>
            <div 
              title={isCollapsed ? item.label : undefined}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 dark:text-slate-400 ${isCollapsed ? "justify-center" : ""}`}
            >
              {item.icon && <item.icon className="h-4 w-4 shrink-0 text-slate-400" />}
              {!isCollapsed && <span className="flex-1 truncate">{item.label}</span>}
              {!isCollapsed && item.badge && (
                <span className="rounded bg-[#22C55E] px-1.5 py-0.5 text-[10px] font-bold text-white shrink-0">
                  {item.badge}
                </span>
              )}
              {!isCollapsed && <ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${isExpanded ? "rotate-180" : ""}`} />}
            </div>
            {isExpanded && !isCollapsed && (
              <div className="mt-1 flex flex-col gap-1">
                {item.items.map((subItem: any) => renderItem(subItem, true))}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <>
      {isMobileOpen && (
        <div 
          className="fixed inset-0 z-40 bg-slate-900/50 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}
      <aside className={`fixed inset-y-0 left-0 z-50 flex shrink-0 flex-col border-r border-slate-200 bg-white transition-transform duration-300 dark:border-slate-800 dark:bg-slate-950 lg:static lg:translate-x-0 ${isCollapsed ? "lg:w-[72px]" : "w-[255px]"} ${isMobileOpen ? "translate-x-0" : "-translate-x-full"}`}>
        {/* Logo Area */}
        <div className={`flex items-center p-5 ${isCollapsed ? "lg:justify-center lg:px-3" : "gap-3 justify-between"}`}>
          <div className="flex items-center gap-3 overflow-hidden">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#16A05D] text-white">
              <Mic className="h-5 w-5" />
            </div>
            {(!isCollapsed || isMobileOpen) && (
              <div className="whitespace-nowrap lg:block">
                <h1 className="text-[17px] font-bold leading-none tracking-tight text-[#171A1C] dark:text-white">VoicePilot</h1>
                <p className="text-[11px] font-medium text-slate-500 dark:text-slate-400">AI Voice Agents</p>
              </div>
            )}
          </div>
          <button 
            onClick={onClose}
            className="flex items-center justify-center rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 lg:hidden dark:hover:bg-slate-800 dark:hover:text-slate-300"
          >
            <X className="h-5 w-5" />
          </button>
          <button 
            onClick={() => setIsCollapsed(!isCollapsed)}
            className={`hidden shrink-0 items-center justify-center rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 lg:flex dark:hover:bg-slate-800 dark:hover:text-slate-300 ${isCollapsed ? "mt-4 !hidden" : ""}`}
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        </div>
      {isCollapsed && (
        <div className="flex justify-center pb-2">
          <button 
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="flex items-center justify-center rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Navigation Areas */}
      <div className="relative flex-1 overflow-y-auto px-3 py-4 custom-scrollbar">
        <div className="mb-6">
          {mainNav.map((item) => renderItem(item))}
        </div>

        <div className="mb-6">
          {!isCollapsed && <h3 className="mb-3 px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Operations</h3>}
          {isCollapsed && <div className="mb-3 h-px bg-slate-200 mx-2 dark:bg-slate-800"></div>}
          {operationsNav.map((item) => renderItem(item))}
        </div>

        <div className="mb-6">
          {!isCollapsed && <h3 className="mb-3 px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Compliance & Data</h3>}
          {isCollapsed && <div className="mb-3 h-px bg-slate-200 mx-2 dark:bg-slate-800"></div>}
          {complianceNav.map((item) => renderItem(item))}
        </div>

        <div className="mb-6">
          {!isCollapsed && <h3 className="mb-3 px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Settings & Account</h3>}
          {isCollapsed && <div className="mb-3 h-px bg-slate-200 mx-2 dark:bg-slate-800"></div>}
          {settingsNav.map((item) => renderItem(item))}
        </div>
      </div>

      {/* User Profile */}
      <div className="border-t border-slate-200 p-4 dark:border-slate-800">
        <div className={`flex items-center rounded-lg p-2 hover:bg-slate-50 dark:hover:bg-slate-900 cursor-pointer ${isCollapsed ? "justify-center" : "gap-3"}`}>
          <img 
            src="https://api.dicebear.com/7.x/notionists/svg?seed=John&backgroundColor=EAF8F0" 
            alt="John Carter" 
            className="h-9 w-9 shrink-0 rounded-full border border-slate-200 dark:border-slate-700 bg-slate-100"
          />
          {!isCollapsed && (
            <>
              <div className="flex-1 overflow-hidden">
                <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">John Carter</p>
                <p className="truncate text-xs text-slate-500 dark:text-slate-400">Admin</p>
              </div>
              <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
            </>
          )}
        </div>
      </div>
    </aside>
    </>
  );
}

function TopHeader({ slug, onMenuToggle }: { slug: string; onMenuToggle: () => void }) {
  const { session, viewAsRequested } = useClientRealm();
  const me = useMe(session);
  return (
    <header className="sticky top-0 z-10 flex h-[72px] shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 lg:px-8 dark:border-slate-800 dark:bg-slate-950">
      <div className="flex items-center gap-3">
        <button 
          onClick={onMenuToggle}
          className="flex h-9 w-9 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100 lg:hidden dark:text-slate-400 dark:hover:bg-slate-800"
        >
          <Menu className="h-5 w-5" />
        </button>
        <h1 className="text-xl lg:text-2xl font-bold tracking-tight text-slate-900 dark:text-white">Dashboard</h1>
      </div>

      <div className="flex items-center gap-2 lg:gap-4">
        {/* Campaign Selector */}
        <button className="hidden h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-50 lg:flex dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800">
          All Campaigns
          <ChevronDown className="h-4 w-4 text-slate-400" />
        </button>

        {/* Date Selector */}
        <button className="hidden h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-50 lg:flex dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800">
          <Calendar className="h-4 w-4 text-slate-400" />
          May 5 – May 11, 2025
          <ChevronDown className="h-4 w-4 text-slate-400" />
        </button>

        <div className="hidden h-5 w-px bg-slate-200 lg:block dark:bg-slate-800" />

        {/* Action Icons */}
        <button className="hidden h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 sm:flex dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-slate-800">
          <MessageSquare className="h-4 w-4" />
        </button>

        <button className="relative flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-slate-800">
          <Bell className="h-4 w-4" />
          <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full border-2 border-white bg-red-500 text-[9px] font-bold text-white dark:border-slate-950">
            3
          </span>
        </button>

        {/* Availability */}
        <button className="flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-2 lg:px-3 lg:pl-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800">
          <div className="h-2 w-2 shrink-0 rounded-full bg-[#22C55E]" />
          <span className="hidden lg:inline">Available</span>
          <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
        </button>
      </div>
    </header>
  );
}

function ViewAsBanner({ slug }: { slug: string }) {
  const { session, viewAsRequested } = useClientRealm();
  const me = useMe(session);

  if (me.data?.impersonating) {
    return (
      <div className="bg-amber-500 px-4 py-1.5 text-center text-xs font-semibold text-amber-950">
        Viewing as {me.data.organization?.name ?? slug} — read only. Every page view is
        logged, and anything that would change this account is refused.
      </div>
    );
  }

  if (viewAsRequested && !me.data?.impersonating && me.error != null) {
    return (
      <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 dark:border-rose-900 dark:bg-rose-950">
        <ProblemNotice error={me.error} />
        <p className="mt-2 text-xs text-rose-800 dark:text-rose-300">
          This page was opened as an operator. Open it from the admin console, or{" "}
          <Link href={`/c/${slug}`} className="underline">
            continue as a normal user
          </Link>
          .
        </p>
      </div>
    );
  }

  return null;
}

export default function ClientRealmLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  
  return (
    <Providers>
      <div className="fixed inset-0 flex overflow-hidden bg-[#FAFAFA] font-sans dark:bg-slate-950">
        <ClientRealmProvider
          slug={slug}
          fallback={
            <div className="flex h-full w-full items-center justify-center">
              <div className="w-96"><Skeleton rows={8} /></div>
            </div>
          }
        >
          <Sidebar slug={slug} isMobileOpen={isMobileOpen} onClose={() => setIsMobileOpen(false)} />
          <div className="flex flex-1 flex-col overflow-hidden">
            <ViewAsBanner slug={slug} />
            <TopHeader slug={slug} onMenuToggle={() => setIsMobileOpen(true)} />
            <main className="relative flex-1 overflow-y-auto px-4 py-4 lg:px-8 lg:py-6">
              <div className="mx-auto max-w-[1280px]">
                {children}
              </div>
            </main>
          </div>
        </ClientRealmProvider>
      </div>
      <style dangerouslySetInnerHTML={{__html: `
        .custom-scrollbar::-webkit-scrollbar {
          width: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background-color: #cbd5e1;
          border-radius: 20px;
        }
        .dark .custom-scrollbar::-webkit-scrollbar-thumb {
          background-color: #334155;
        }
      `}} />
    </Providers>
  );
}
