import React from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutGrid,
  Upload,
  Sparkles,
  Settings,
  LogOut,
  BellDot,
  Search,
  CreditCard,
  HelpCircle,
} from "lucide-react";
import { Logo } from "./Logo";
import { useAppStore } from "@/store/useAppStore";
import { DASHBOARD } from "@/constants/testIds";

const NAV = [
  { key: "dashboard", label: "Projects", icon: LayoutGrid, path: "/dashboard" },
  { key: "upload", label: "New Upload", icon: Upload, path: "/upload" },
  { key: "clips", label: "Clip Library", icon: Sparkles, path: "/clips/prj_001" },
  { key: "billing", label: "Billing", icon: CreditCard, path: "/dashboard" },
  { key: "settings", label: "Settings", icon: Settings, path: "/dashboard" },
  { key: "help", label: "Help", icon: HelpCircle, path: "/dashboard" },
];

export const AppShell = ({ children, title, subtitle, actions }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const user = useAppStore((s) => s.user);
  const signOut = useAppStore((s) => s.signOut);

  const active = (path) => location.pathname === path;

  return (
    <div className="min-h-screen w-full text-white bg-[#060608] flex">
      {/* Sidebar */}
      <aside className="w-[240px] shrink-0 border-r border-[#1c1c24] bg-[#0a0a0f] flex flex-col">
        <div className="h-16 flex items-center px-5 border-b border-[#1c1c24]">
          <Logo />
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          <p className="text-[10px] uppercase tracking-[0.22em] text-[#5a5a66] px-3 mb-2">
            Workspace
          </p>
          {NAV.slice(0, 3).map((item) => {
            const Icon = item.icon;
            const isActive = active(item.path);
            return (
              <Link
                key={item.key}
                to={item.path}
                data-testid={DASHBOARD.sidebarLink(item.key)}
                className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-[#7c3aed]/15 text-white border border-[#7c3aed]/30"
                    : "text-[#a1a1aa] hover:text-white hover:bg-white/5 border border-transparent"
                }`}
              >
                <Icon size={16} strokeWidth={2} />
                {item.label}
              </Link>
            );
          })}

          <p className="text-[10px] uppercase tracking-[0.22em] text-[#5a5a66] px-3 mt-6 mb-2">
            Account
          </p>
          {NAV.slice(3).map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.key}
                to={item.path}
                data-testid={DASHBOARD.sidebarLink(item.key)}
                className="flex items-center gap-3 px-3 py-2 rounded-md text-sm text-[#a1a1aa] hover:text-white hover:bg-white/5 transition-colors"
              >
                <Icon size={16} strokeWidth={2} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Upgrade card */}
        <div className="m-3 p-4 rounded-xl border border-[#2a2a35] bg-gradient-to-br from-[#7c3aed]/15 via-[#111116] to-[#111116] relative overflow-hidden">
          <div className="absolute -top-6 -right-6 w-24 h-24 rounded-full bg-[#7c3aed]/25 blur-2xl" />
          <p className="text-xs uppercase tracking-wider text-[#a78bfa] mb-1">
            Studio Plan
          </p>
          <p className="text-sm font-semibold mb-2">Unlock 4K exports</p>
          <p className="text-xs text-[#a1a1aa] mb-3 leading-relaxed">
            Team seats, API access & priority renders.
          </p>
          <button className="text-xs font-semibold text-white bg-[#7c3aed] hover:bg-[#6d28d9] px-3 py-1.5 rounded-md w-full transition-colors">
            Upgrade
          </button>
        </div>

        {/* User pill */}
        <div className="border-t border-[#1c1c24] p-3 flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-[#7c3aed] to-[#c026d3] flex items-center justify-center text-sm font-bold">
            {(user?.name?.[0] || "R").toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold truncate">
              {user?.name || "Rahul K"}
            </p>
            <p className="text-[11px] text-[#71717a] truncate">
              {user?.plan || "Creator"} · {user?.email || "creator@shotvi.app"}
            </p>
          </div>
          <button
            data-testid={DASHBOARD.userMenu}
            onClick={() => {
              signOut();
              navigate("/");
            }}
            className="p-2 rounded-md hover:bg-white/5 text-[#a1a1aa] hover:text-white transition-colors"
            title="Sign out"
          >
            <LogOut size={15} />
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0 flex flex-col">
        {/* Top bar */}
        <header className="h-16 border-b border-[#1c1c24] bg-[#060608]/80 backdrop-blur-xl px-8 flex items-center justify-between sticky top-0 z-30">
          <div className="min-w-0">
            {title && (
              <h1 className="font-display text-xl font-semibold tracking-tight text-white truncate">
                {title}
              </h1>
            )}
            {subtitle && (
              <p className="text-xs text-[#a1a1aa] mt-0.5 truncate">
                {subtitle}
              </p>
            )}
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden md:flex items-center gap-2 h-9 px-3 rounded-md bg-[#111116] border border-[#2a2a35] w-72">
              <Search size={14} className="text-[#71717a]" />
              <input
                placeholder="Search projects, clips..."
                className="bg-transparent border-0 outline-none text-sm text-white placeholder-[#71717a] w-full"
              />
              <span className="text-[10px] text-[#5a5a66] px-1.5 py-0.5 rounded border border-[#2a2a35]">
                ⌘K
              </span>
            </div>
            <button className="w-9 h-9 flex items-center justify-center rounded-md bg-[#111116] border border-[#2a2a35] text-[#a1a1aa] hover:text-white transition-colors relative">
              <BellDot size={15} />
              <span className="absolute top-2 right-2 w-1.5 h-1.5 rounded-full bg-[#7c3aed]" />
            </button>
            {actions}
          </div>
        </header>

        <div className="flex-1 min-h-0">{children}</div>
      </main>
    </div>
  );
};

export default AppShell;
