import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Mail, Lock, User, ArrowLeft, ArrowRight } from "lucide-react";
import { Logo } from "@/components/shotvi/Logo";
import { useAppStore } from "@/store/useAppStore";
import { AUTH } from "@/constants/testIds";

export default function Auth() {
  const [tab, setTab] = useState("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const signIn = useAppStore((s) => s.signIn);
  const navigate = useNavigate();

  const handleSubmit = (e) => {
    e.preventDefault();
    signIn(email || "creator@shotvi.app");
    navigate("/dashboard");
  };

  return (
    <div
      data-testid={AUTH.root}
      className="min-h-screen w-full bg-[#060608] text-white flex relative overflow-hidden"
    >
      {/* Left visual */}
      <div className="hidden lg:flex w-1/2 relative border-r border-[#1c1c24]">
        <img
          src="https://images.unsplash.com/photo-1563089145-599997674d42"
          alt=""
          className="absolute inset-0 w-full h-full object-cover opacity-40"
        />
        <div className="absolute inset-0 bg-gradient-to-br from-[#060608]/40 via-[#060608]/70 to-[#060608]" />
        <div className="absolute inset-0 hero-glow opacity-90" />
        <div className="relative z-10 flex flex-col justify-between p-12 w-full">
          <Logo size="md" />
          <div>
            <p className="text-xs uppercase tracking-[0.28em] text-[#c4b5fd] mb-6">
              For Regional Creators
            </p>
            <h1 className="font-display text-5xl xl:text-6xl font-bold tracking-tight leading-[1.05] mb-6">
              The pro editor
              <br />
              for <span className="italic text-[#c4b5fd]">Telugu</span> Shorts.
            </h1>
            <p className="text-[#a1a1aa] max-w-md leading-relaxed">
              Join 12,000+ creators shipping viral Reels & Shorts every week —
              in the language their audience speaks.
            </p>
            <div className="mt-10 flex gap-6">
              {[
                { n: "94", l: "Avg. virality" },
                { n: "4 min", l: "Time to first clip" },
                { n: "12K+", l: "Creators" },
              ].map((s) => (
                <div key={s.l}>
                  <p className="font-display text-3xl font-bold">{s.n}</p>
                  <p className="text-xs text-[#71717a] mt-1">{s.l}</p>
                </div>
              ))}
            </div>
          </div>
          <p className="text-xs text-[#5a5a66]">
            "నా podcast నుండి 8 viral clips వచ్చాయి — no editor needed."
            <br />
            <span className="text-[#a1a1aa]">— Priya S., Telugu Tech Podcaster</span>
          </p>
        </div>
      </div>

      {/* Right form */}
      <div className="flex-1 flex items-center justify-center p-6 lg:p-12 relative">
        <Link
          to="/"
          data-testid={AUTH.backHome}
          className="absolute top-6 left-6 flex items-center gap-1.5 text-xs text-[#a1a1aa] hover:text-white transition-colors"
        >
          <ArrowLeft size={14} /> Back home
        </Link>

        <div className="w-full max-w-md">
          <div className="lg:hidden mb-8">
            <Logo />
          </div>
          <div className="mb-8">
            <h2 className="font-display text-3xl font-bold tracking-tight mb-2">
              {tab === "signin" ? "Welcome back" : "Create your account"}
            </h2>
            <p className="text-sm text-[#a1a1aa]">
              {tab === "signin"
                ? "Sign in to keep clipping. Your projects are waiting."
                : "Start with 3 free projects. No card required."}
            </p>
          </div>

          {/* Tabs */}
          <div className="flex p-1 bg-[#0b0b10] border border-[#2a2a35] rounded-md mb-6">
            <button
              data-testid={AUTH.tabSignIn}
              onClick={() => setTab("signin")}
              className={`flex-1 text-sm font-medium py-2 rounded transition-colors ${
                tab === "signin"
                  ? "bg-[#7c3aed] text-white"
                  : "text-[#a1a1aa] hover:text-white"
              }`}
            >
              Sign in
            </button>
            <button
              data-testid={AUTH.tabSignUp}
              onClick={() => setTab("signup")}
              className={`flex-1 text-sm font-medium py-2 rounded transition-colors ${
                tab === "signup"
                  ? "bg-[#7c3aed] text-white"
                  : "text-[#a1a1aa] hover:text-white"
              }`}
            >
              Sign up
            </button>
          </div>

          <button
            data-testid={AUTH.googleBtn}
            onClick={handleSubmit}
            className="w-full flex items-center justify-center gap-2 bg-white text-black text-sm font-semibold py-2.5 rounded-md hover:bg-[#e5e5e5] transition-colors mb-4"
          >
            <svg width="16" height="16" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              />
            </svg>
            Continue with Google
          </button>

          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-[#2a2a35]" />
            </div>
            <div className="relative flex justify-center">
              <span className="bg-[#060608] px-3 text-[11px] uppercase tracking-widest text-[#71717a]">
                or with email
              </span>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {tab === "signup" && (
              <div>
                <label className="text-xs uppercase tracking-widest text-[#71717a] mb-2 block">
                  Full Name
                </label>
                <div className="relative">
                  <User
                    size={15}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-[#71717a]"
                  />
                  <input
                    data-testid={AUTH.name}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    type="text"
                    placeholder="Rahul Kumar"
                    className="w-full bg-[#0b0b10] border border-[#2a2a35] rounded-md py-2.5 pl-10 pr-3 text-sm text-white placeholder-[#5a5a66] focus:border-[#7c3aed] focus:ring-1 focus:ring-[#7c3aed] outline-none transition-colors"
                  />
                </div>
              </div>
            )}
            <div>
              <label className="text-xs uppercase tracking-widest text-[#71717a] mb-2 block">
                Email
              </label>
              <div className="relative">
                <Mail
                  size={15}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-[#71717a]"
                />
                <input
                  data-testid={AUTH.email}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  type="email"
                  placeholder="you@studio.com"
                  className="w-full bg-[#0b0b10] border border-[#2a2a35] rounded-md py-2.5 pl-10 pr-3 text-sm text-white placeholder-[#5a5a66] focus:border-[#7c3aed] focus:ring-1 focus:ring-[#7c3aed] outline-none transition-colors"
                />
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs uppercase tracking-widest text-[#71717a]">
                  Password
                </label>
                {tab === "signin" && (
                  <a
                    href="#"
                    className="text-xs text-[#a78bfa] hover:text-white transition-colors"
                  >
                    Forgot?
                  </a>
                )}
              </div>
              <div className="relative">
                <Lock
                  size={15}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-[#71717a]"
                />
                <input
                  data-testid={AUTH.password}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  type="password"
                  placeholder="••••••••"
                  className="w-full bg-[#0b0b10] border border-[#2a2a35] rounded-md py-2.5 pl-10 pr-3 text-sm text-white placeholder-[#5a5a66] focus:border-[#7c3aed] focus:ring-1 focus:ring-[#7c3aed] outline-none transition-colors"
                />
              </div>
            </div>
            <button
              data-testid={AUTH.submit}
              type="submit"
              className="w-full flex items-center justify-center gap-2 bg-[#7c3aed] hover:bg-[#6d28d9] text-white text-sm font-semibold py-2.5 rounded-md transition-colors shadow-[0_10px_30px_-10px_rgba(124,58,237,0.6)]"
            >
              {tab === "signin" ? "Sign in" : "Create account"}
              <ArrowRight size={14} />
            </button>
          </form>

          <p className="text-xs text-[#71717a] text-center mt-6">
            By continuing you agree to our{" "}
            <a href="#" className="text-[#a1a1aa] hover:text-white">
              Terms
            </a>{" "}
            &{" "}
            <a href="#" className="text-[#a1a1aa] hover:text-white">
              Privacy Policy
            </a>
            .
          </p>
        </div>
      </div>
    </div>
  );
}
