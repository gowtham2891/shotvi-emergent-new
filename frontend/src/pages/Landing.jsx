import React from "react";
import { Link } from "react-router-dom";
import {
  Wand2,
  Languages,
  Scissors,
  Rocket,
  Check,
  ArrowRight,
  Sparkles,
  Play,
  Zap,
  Youtube,
} from "lucide-react";
import { Logo } from "@/components/shotvi/Logo";
import { LANDING } from "@/constants/testIds";
import { PRICING_TIERS } from "@/data/mockData";

const Feature = ({ icon: Icon, title, desc, big, className = "", testId }) => (
  <div
    data-testid={testId}
    className={`group relative overflow-hidden rounded-2xl border border-[#2a2a35] bg-gradient-to-br from-[#111116] to-[#0b0b10] p-6 hover:border-[#7c3aed]/40 transition-colors ${className}`}
  >
    <div className="absolute -top-16 -right-16 w-40 h-40 rounded-full bg-[#7c3aed]/10 blur-3xl group-hover:bg-[#7c3aed]/20 transition-colors" />
    <div className="relative">
      <div
        className={`inline-flex items-center justify-center rounded-lg bg-[#7c3aed]/15 border border-[#7c3aed]/25 mb-4 ${
          big ? "w-12 h-12" : "w-10 h-10"
        }`}
      >
        <Icon size={big ? 22 : 18} className="text-[#c4b5fd]" />
      </div>
      <h3
        className={`font-display font-semibold text-white mb-2 tracking-tight ${
          big ? "text-2xl" : "text-lg"
        }`}
      >
        {title}
      </h3>
      <p className="text-sm text-[#a1a1aa] leading-relaxed">{desc}</p>
    </div>
  </div>
);

export default function Landing() {
  return (
    <div
      data-testid={LANDING.root}
      className="min-h-screen w-full text-white bg-[#060608] relative grain"
    >
      {/* Nav */}
      <nav className="sticky top-0 z-40 border-b border-[#1c1c24] bg-[#060608]/80 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo />
          <div className="hidden md:flex items-center gap-8 text-sm text-[#a1a1aa]">
            <a href="#features" className="hover:text-white transition-colors">
              Features
            </a>
            <a href="#how" className="hover:text-white transition-colors">
              How it works
            </a>
            <a href="#pricing" className="hover:text-white transition-colors">
              Pricing
            </a>
            <a
              href="#creators"
              className="hover:text-white transition-colors"
            >
              Creators
            </a>
          </div>
          <div className="flex items-center gap-2">
            <Link
              to="/auth"
              data-testid={LANDING.navSignIn}
              className="hidden sm:inline-flex text-sm text-[#a1a1aa] hover:text-white px-4 py-2 rounded-md transition-colors"
            >
              Sign in
            </Link>
            <Link
              to="/auth"
              data-testid={LANDING.navGetStarted}
              className="inline-flex items-center gap-1.5 bg-white text-black text-sm font-semibold px-4 py-2 rounded-md hover:bg-[#e5e5e5] transition-colors"
            >
              Get started <ArrowRight size={14} />
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 hero-glow" />
        <div className="absolute inset-0 grid-lines opacity-40" />
        <div className="relative max-w-7xl mx-auto px-6 pt-24 pb-24 lg:pt-32 lg:pb-32">
          <div className="max-w-4xl">
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-[#7c3aed]/40 bg-[#7c3aed]/10 text-[11px] uppercase tracking-[0.22em] text-[#c4b5fd] mb-8">
              <Sparkles size={12} />
              Made for Telugu creators
            </div>
            <h1 className="font-display text-5xl md:text-6xl lg:text-7xl font-bold tracking-tight leading-[1.02] mb-6">
              Turn long Telugu videos
              <br />
              into <span className="italic text-[#c4b5fd]">viral</span> Shorts
              <br />
              <span className="bg-gradient-to-r from-white via-[#c4b5fd] to-[#f0abfc] bg-clip-text text-transparent">
                automatically.
              </span>
            </h1>
            <p className="text-lg text-[#a1a1aa] max-w-2xl mb-10 leading-relaxed">
              Shotvi finds the highest-scoring 30-second moments from your
              podcasts, interviews & vlogs — then adds word-perfect Telugu +
              Tenglish captions in one click. No editor. No English-only bias.
            </p>

            <div className="flex flex-wrap items-center gap-3 mb-10">
              <Link
                to="/auth"
                data-testid={LANDING.heroCta}
                className="inline-flex items-center gap-2 bg-[#7c3aed] hover:bg-[#6d28d9] text-white font-semibold px-6 py-3 rounded-md transition-colors shadow-[0_10px_40px_-10px_rgba(124,58,237,0.7)]"
              >
                Start clipping free <ArrowRight size={16} />
              </Link>
              <button
                data-testid={LANDING.heroSecondaryCta}
                className="inline-flex items-center gap-2 bg-[#111116] border border-[#2a2a35] hover:border-[#7c3aed]/50 text-white font-medium px-6 py-3 rounded-md transition-colors"
              >
                <Play size={14} /> Watch 60-sec demo
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-[#71717a]">
              <span className="inline-flex items-center gap-2">
                <Check size={13} className="text-[#10b981]" /> No credit card
              </span>
              <span className="inline-flex items-center gap-2">
                <Check size={13} className="text-[#10b981]" /> 3 free projects/mo
              </span>
              <span className="inline-flex items-center gap-2">
                <Check size={13} className="text-[#10b981]" /> Telugu + Tenglish + Hindi
              </span>
            </div>
          </div>

          {/* Hero mock preview */}
          <div className="mt-16 relative">
            <div className="rounded-2xl border border-[#2a2a35] bg-[#0b0b10] p-2 shadow-[0_40px_80px_-20px_rgba(124,58,237,0.35)] max-w-5xl mx-auto">
              <div className="rounded-xl overflow-hidden bg-[#060608] relative">
                <div className="grid grid-cols-12 gap-2 p-3">
                  {/* Left */}
                  <div className="col-span-3 space-y-2">
                    {[1, 2, 3, 4].map((i) => (
                      <div
                        key={i}
                        className="h-14 rounded-md bg-[#111116] border border-[#2a2a35] flex items-center gap-2 px-2"
                      >
                        <div className="w-9 h-9 rounded bg-gradient-to-br from-[#7c3aed] to-[#c026d3]" />
                        <div className="flex-1">
                          <div className="h-1.5 w-3/4 rounded bg-[#2a2a35] mb-1" />
                          <div className="h-1 w-1/2 rounded bg-[#2a2a35]" />
                        </div>
                      </div>
                    ))}
                  </div>
                  {/* Center 9:16 mock */}
                  <div className="col-span-5 flex items-center justify-center">
                    <div className="aspect-[9/16] max-h-[360px] w-full rounded-lg bg-gradient-to-br from-[#1a0b2e] via-[#0f0817] to-black relative overflow-hidden border border-[#2a2a35] flex items-end justify-center">
                      <img
                        src="https://images.pexels.com/photos/36917952/pexels-photo-36917952.jpeg"
                        alt=""
                        className="absolute inset-0 w-full h-full object-cover opacity-70"
                      />
                      <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-black/40" />
                      <div className="relative pb-10 px-4 text-center">
                        <div className="caption-bold-yellow text-2xl leading-tight">
                          ఈ ఒక్క <span className="caption-word-highlight">AI</span>
                          <br /> tool మీ life
                          <br /> మార్చేస్తుంది!
                        </div>
                      </div>
                      <div className="absolute top-3 left-3 text-[10px] px-2 py-0.5 rounded-full bg-[#7c3aed]/80 backdrop-blur-sm">
                        94 · Viral
                      </div>
                    </div>
                  </div>
                  {/* Right */}
                  <div className="col-span-4 space-y-2">
                    <div className="rounded-md bg-[#111116] border border-[#2a2a35] p-3">
                      <p className="text-[10px] uppercase tracking-widest text-[#71717a] mb-2">
                        Caption Style
                      </p>
                      <div className="grid grid-cols-2 gap-1.5">
                        <div className="h-10 rounded bg-[#1a1a24] border border-[#7c3aed] flex items-center justify-center caption-bold-yellow text-xs">
                          BOLD
                        </div>
                        <div className="h-10 rounded bg-[#1a1a24] border border-[#2a2a35] flex items-center justify-center caption-neon-green text-xs">
                          NEON
                        </div>
                        <div className="h-10 rounded bg-[#1a1a24] border border-[#2a2a35] flex items-center justify-center caption-fire-gradient text-xs">
                          FIRE
                        </div>
                        <div className="h-10 rounded bg-[#1a1a24] border border-[#2a2a35] flex items-center justify-center caption-clean-white text-xs">
                          CLEAN
                        </div>
                      </div>
                    </div>
                    <div className="rounded-md bg-[#111116] border border-[#2a2a35] p-3">
                      <p className="text-[10px] uppercase tracking-widest text-[#71717a] mb-2">
                        Virality
                      </p>
                      <div className="flex items-end gap-1 h-14">
                        {[40, 65, 82, 94, 71, 58, 47].map((v, i) => (
                          <div
                            key={i}
                            className="flex-1 rounded-t bg-gradient-to-t from-[#7c3aed] to-[#c026d3]"
                            style={{ height: `${v}%` }}
                          />
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
                {/* Timeline strip */}
                <div className="h-10 bg-[#0a0a0f] border-t border-[#2a2a35] flex items-center px-3 gap-1">
                  {Array.from({ length: 50 }).map((_, i) => (
                    <div
                      key={i}
                      className="wave-bar w-0.5"
                      style={{ height: `${20 + Math.random() * 60}%` }}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features bento */}
      <section id="features" className="relative py-24">
        <div className="max-w-7xl mx-auto px-6">
          <div className="max-w-2xl mb-14">
            <p className="text-xs uppercase tracking-[0.24em] text-[#a78bfa] mb-4">
              Features
            </p>
            <h2 className="font-display text-4xl md:text-5xl font-bold tracking-tight mb-4">
              Everything a regional creator actually needs.
            </h2>
            <p className="text-[#a1a1aa] text-lg leading-relaxed">
              Built ground-up for Telugu, Tenglish & Hindi speech. Not a
              translated English tool.
            </p>
          </div>

          <div className="grid grid-cols-12 gap-4">
            <Feature
              testId={LANDING.featureCard("ai-clip")}
              className="col-span-12 lg:col-span-8 min-h-[280px]"
              icon={Wand2}
              big
              title="AI clip selection tuned for Telugu speech patterns"
              desc="Our virality model understands Tenglish code-switching, hook lines, punchlines & long silences unique to Indian podcasts. Get 6–12 shareable moments per hour of footage — ranked."
            />
            <Feature
              testId={LANDING.featureCard("captions")}
              className="col-span-12 lg:col-span-4 min-h-[280px]"
              icon={Languages}
              title="Word-accurate Telugu captions"
              desc="Custom ASR trained on Telugu, Tenglish & Hindi. Handles మీ/నా mixed with English words natively."
            />
            <Feature
              testId={LANDING.featureCard("editor")}
              className="col-span-12 lg:col-span-4"
              icon={Scissors}
              title="WYSIWYG editor"
              desc="Word-level timeline, split, and caption styling with live preview. Feels like CapCut, works in browser."
            />
            <Feature
              testId={LANDING.featureCard("export")}
              className="col-span-12 lg:col-span-4"
              icon={Rocket}
              title="One-click export"
              desc="9:16 · 1080p · burn-in captions. Direct download, no rendering queue on paid plans."
            />
            <Feature
              testId={LANDING.featureCard("youtube")}
              className="col-span-12 lg:col-span-4"
              icon={Youtube}
              title="Paste any YouTube link"
              desc="Import directly from a URL — no download, no re-upload. Works for any Telugu channel."
            />
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="relative py-24 border-t border-[#1c1c24]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="mb-14 max-w-2xl">
            <p className="text-xs uppercase tracking-[0.24em] text-[#a78bfa] mb-4">
              How it works
            </p>
            <h2 className="font-display text-4xl md:text-5xl font-bold tracking-tight">
              From 1-hour podcast to 10 viral clips in 4 minutes.
            </h2>
          </div>
          <div className="grid md:grid-cols-4 gap-4">
            {[
              {
                n: "01",
                t: "Upload or paste URL",
                d: "Drop a file up to 2 hours, or paste any YouTube link.",
              },
              {
                n: "02",
                t: "Pick your language",
                d: "Telugu, Tenglish, Hindi or English — we transcribe accurately.",
              },
              {
                n: "03",
                t: "AI picks the best clips",
                d: "Virality score, hook line & duration surfaced per clip.",
              },
              {
                n: "04",
                t: "Style & export",
                d: "Choose a caption preset, tweak in the editor, hit export.",
              },
            ].map((s) => (
              <div
                key={s.n}
                className="rounded-xl border border-[#2a2a35] bg-[#0b0b10] p-6 hover:border-[#7c3aed]/40 transition-colors"
              >
                <p className="font-mono text-[11px] text-[#7c3aed] mb-6 tracking-widest">
                  STEP {s.n}
                </p>
                <h3 className="font-display font-semibold text-lg mb-2">
                  {s.t}
                </h3>
                <p className="text-sm text-[#a1a1aa] leading-relaxed">{s.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="relative py-24 border-t border-[#1c1c24]">
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-center mb-14">
            <p className="text-xs uppercase tracking-[0.24em] text-[#a78bfa] mb-4">
              Pricing
            </p>
            <h2 className="font-display text-4xl md:text-5xl font-bold tracking-tight mb-4">
              Priced for Indian creators.
            </h2>
            <p className="text-[#a1a1aa] text-lg">
              Start free. Upgrade when you go viral.
            </p>
          </div>
          <div className="grid md:grid-cols-3 gap-5 max-w-5xl mx-auto">
            {PRICING_TIERS.map((t) => (
              <div
                key={t.id}
                data-testid={LANDING.pricingCard(t.id)}
                className={`relative rounded-2xl border p-7 flex flex-col ${
                  t.highlighted
                    ? "border-[#7c3aed] bg-gradient-to-b from-[#7c3aed]/10 to-[#0b0b10] pulse-glow"
                    : "border-[#2a2a35] bg-[#0b0b10]"
                }`}
              >
                {t.highlighted && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 text-[10px] uppercase tracking-widest bg-[#7c3aed] text-white px-3 py-1 rounded-full">
                    {t.tag}
                  </span>
                )}
                <div className="flex items-center justify-between mb-5">
                  <h3 className="font-display font-semibold text-xl">
                    {t.name}
                  </h3>
                  {!t.highlighted && (
                    <span className="text-[10px] uppercase tracking-widest text-[#71717a]">
                      {t.tag}
                    </span>
                  )}
                </div>
                <div className="mb-6">
                  <span className="font-display text-4xl font-bold">
                    {t.price}
                  </span>
                  <span className="text-sm text-[#71717a] ml-2">
                    {t.period}
                  </span>
                </div>
                <ul className="space-y-3 mb-8 flex-1">
                  {t.features.map((f) => (
                    <li
                      key={f}
                      className="flex items-start gap-2 text-sm text-[#d4d4d8]"
                    >
                      <Check
                        size={14}
                        className="text-[#7c3aed] mt-0.5 shrink-0"
                      />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  to="/auth"
                  data-testid={LANDING.pricingCta(t.id)}
                  className={`text-center text-sm font-semibold py-2.5 rounded-md transition-colors ${
                    t.highlighted
                      ? "bg-[#7c3aed] hover:bg-[#6d28d9] text-white"
                      : "bg-[#1a1a24] border border-[#2a2a35] hover:bg-[#2a2a35] text-white"
                  }`}
                >
                  {t.cta}
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="relative py-24 border-t border-[#1c1c24] overflow-hidden">
        <div className="absolute inset-0 hero-glow opacity-70" />
        <div className="relative max-w-4xl mx-auto px-6 text-center">
          <Zap className="mx-auto text-[#c4b5fd] mb-6" size={28} />
          <h2 className="font-display text-4xl md:text-6xl font-bold tracking-tight mb-6">
            Your next viral Reel is
            <br />
            <span className="italic text-[#c4b5fd]">already inside</span> your last podcast.
          </h2>
          <p className="text-[#a1a1aa] text-lg mb-8">
            Let Shotvi find it in under 4 minutes.
          </p>
          <Link
            to="/auth"
            data-testid={LANDING.footerCta}
            className="inline-flex items-center gap-2 bg-white text-black font-semibold px-6 py-3 rounded-md hover:bg-[#e5e5e5] transition-colors"
          >
            Try Shotvi free <ArrowRight size={16} />
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-[#1c1c24] py-10">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-4">
          <Logo size="sm" />
          <p className="text-xs text-[#71717a]">
            © 2026 Shotvi Labs. Made in Hyderabad for creators everywhere.
          </p>
          <div className="flex gap-5 text-xs text-[#71717a]">
            <a href="#" className="hover:text-white transition-colors">
              Terms
            </a>
            <a href="#" className="hover:text-white transition-colors">
              Privacy
            </a>
            <a href="#" className="hover:text-white transition-colors">
              Twitter
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
