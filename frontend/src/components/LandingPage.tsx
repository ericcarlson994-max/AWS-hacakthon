"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent, type MouseEvent } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, clearSession, getStoredUser, storeSession } from "@/lib/api";
import type { User } from "@/lib/types";

type El = HTMLElement & {
  _v?: string;
  _k?: number;
  _x?: number;
  _y?: number;
  _f?: HTMLElement[];
  _b?: number;
  _s?: number;
};

const PAL = [
  [240, 243, 248, 0.72],
  [205, 222, 246, 0.8],
  [150, 186, 240, 0.85],
  [31, 111, 229, 0.9],
  [11, 79, 194, 0.92],
];

const CARDS = [
  { type: "CIRCULAR", match: "98%", title: "Circular PKP/HR/2026/03 — Remote work", ref: "§2 · p.1", c: [31, 111, 229], ink: "#fff" },
  { type: "SOP", match: "91%", title: "SOP: Claims Submission", ref: "Step 4 · p.2", c: [11, 79, 194], ink: "#fff" },
  { type: "MINUTES", match: "84%", title: "Minit Mesyuarat Pengurusan Bil. 6/2026", ref: "Item 5.1 · p.2", c: [150, 186, 240], ink: "#0B2A5C" },
  { type: "POLICY", match: "80%", title: "Procurement Policy", ref: "§4 · p.3", c: [205, 222, 246], ink: "#15171C" },
  { type: "GUIDELINE", match: "76%", title: "数据共享指南 — Data sharing", ref: "p.1", c: [74, 141, 236], ink: "#fff" },
  { type: "REPORT", match: "71%", title: "Annual Report on Digital Services 2025", ref: "§3 · p.4", c: [240, 243, 248], ink: "#15171C" },
];

const NUMS = ["1,204", "SOP", "07", "3,118", "2.1/25", "942", "§4.2", "2,876", "031", "p.11", "1,757", "2,511", "214", "REV.3", "12", "0.8s", "98", "640", "15", "Q2"];
const RIBBON = 56;
const TILES = 96;
const DEMO = ["alice", "ben", "chloe", "admin"];
const NAV = ["Product", "Security", "Agencies"];

const cl = (x: number) => Math.min(1, Math.max(0, x));
const ss = (a: number, b: number, x: number) => {
  const t = cl((x - a) / (b - a));
  return t * t * (3 - 2 * t);
};
const L = (a: number, b: number, t: number) => a + (b - a) * t;

const subscribe = (callback: () => void) => {
  window.addEventListener("storage", callback);
  return () => window.removeEventListener("storage", callback);
};
const readUser = () => {
  const user = getStoredUser();
  return user ? JSON.stringify(user) : "";
};

function useStoryAnimation(storyRef: React.RefObject<HTMLDivElement | null>, mouseX: React.RefObject<number | null>) {
  useEffect(() => {
    const story = storyRef.current;
    if (!story) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const cache: Record<string, Element | NodeListOf<Element> | null> = {};
    const one = (s: string) => (cache[s] ??= story.querySelector(s)) as El;
    const all = (s: string) => (cache[`*${s}`] ??= story.querySelectorAll(s)) as NodeListOf<El>;
    const setText = (el: El, v: string) => {
      if (el._v !== v) {
        el._v = v;
        el.textContent = v;
      }
    };
    let lastP = -1;
    let lastVw = -1;
    let frame = 0;

    const tick = (time: number) => {
      const t = reduced ? 0 : time;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const rb = story.getBoundingClientRect();
      const p = cl(-rb.top / (rb.height - vh));
      const pc = p !== lastP || vw !== lastVw;
      lastP = p;
      lastVw = vw;

      if (pc) {
        setText(one("[data-idx]"), p < 0.2 ? "001 — 004" : p < 0.58 ? "002 — 004" : "003 — 004");
        setText(one("[data-scrolllabel]"), p < 0.05 ? "Discover more" : "Scroll");
        const hero = one("[data-hero]");
        hero.style.opacity = String(1 - ss(0.02, 0.1, p));
        hero.style.transform = `translateY(${-ss(0.02, 0.12, p) * 40}px)`;
        one("[data-sun]").style.opacity = String(ss(0.56, 0.72, p) * 0.9);
        one("[data-t2]").style.opacity = String(ss(0.32, 0.38, p) * (1 - ss(0.52, 0.57, p)));
        const t3 = one("[data-t3]");
        const e3 = ss(0.84, 0.93, p);
        t3.style.opacity = String(e3);
        t3.style.transform = `translateY(calc(-50% + ${(1 - e3) * 30}px))`;
        t3.style.pointerEvents = e3 > 0.5 ? "auto" : "none";
      }

      const rib = one("[data-ribbon]");
      const ribOn = p <= 0.32;
      rib.style.visibility = ribOn ? "" : "hidden";
      if (ribOn) {
        const els = all("[data-r]");
        const n = els.length;
        const rs = Math.min(1, vh / 820);
        rib.style.transform = `scale(${rs})`;
        const total = (vw * 1.3) / rs;
        const sp = total / n;
        const speed = reduced ? 0 : 38;
        const peak = 0.55 + Math.sin(t * 0.25) * 0.04;
        els.forEach((el, i) => {
          if (!el._k) {
            const ph0 = i / n;
            const k = 0.5 + 0.5 * Math.sin(ph0 * 13 + 1) * Math.cos(ph0 * 5);
            const c = PAL[k < 0.38 ? 0 : k < 0.55 ? 1 : k < 0.7 ? 2 : k < 0.86 ? 3 : 4]!;
            const bg = `linear-gradient(165deg,rgba(255,255,255,.55),rgba(255,255,255,0) 50%),rgba(${c[0]},${c[1]},${c[2]},${c[3]})`;
            el.querySelectorAll<HTMLElement>("[data-c]").forEach((node) => (node.style.background = bg));
            el._k = 1;
          }
          const u = (((i * sp - time * speed) % total) + total) % total;
          const x = u - total / 2;
          const ph = u / total;
          const g = Math.exp(-(((ph - peak) / 0.05) ** 2));
          const mx = mouseX.current;
          const hv = mx == null ? 0 : Math.exp(-(((x * rs - mx) / 120) ** 2));
          const ex = ss(0.05 + ph * 0.07, 0.17 + ph * 0.07, p);
          const y = Math.sin(ph * 9 + t * 0.5) * 12 - g * 70 - hv * 34 - ex * vh * 1.3;
          const rx = Math.sin(ph * 6.5 + t * 0.3) * 22 + g * 20 + ex * 50;
          const ry = -66 + Math.sin(ph * 4 - t * 0.2) * 14 + hv * 18;
          const edge = Math.min(1, ph * 14, (1 - ph) * 14);
          el.style.transform = `translate3d(${x}px,${y}px,${ex * 260}px) rotateY(${ry}deg) rotateX(${rx}deg) rotateZ(${ex * 30}deg)`;
          el.style.opacity = String(edge);
        });
        all("[data-n]").forEach((num) => {
          if (num._x == null) {
            num._x = Math.random();
            num._y = (Math.random() - 0.5) * 260;
          }
          const u = (((num._x * total - time * speed * 0.6) % total) + total) % total;
          num.style.transform = `translate3d(${u - total / 2}px,${(num._y ?? 0) - ss(0.04, 0.2, p) * vh}px,0)`;
          num.style.opacity = String(0.8 * (1 - ss(0.04, 0.14, p)) * Math.min(1, (u / total) * 10, (1 - u / total) * 10));
        });
      }

      const cam = one("[data-cam]");
      const camOn = p >= 0.16;
      cam.style.visibility = camOn ? "" : "hidden";
      if (!camOn) return;
      const a = ss(0.16, 0.32, p);
      const c = ss(0.6, 0.74, p);
      const d = ss(0.76, 0.93, p);
      if (pc) {
        const sc = Math.min(1, vw / 1300) * L(L(L(0.5, 0.82, a), 1, c), 1.3, d);
        const rx = L(L(62, 55, c), 48, d);
        const rz = L(L(-42, -32, c), -24, d) + ss(0.32, 0.6, p) * 6;
        const tx = d * vw * 0.26;
        const ty = L((1 - a) * 80, vh * 0.1, d);
        cam.style.transform = `translate(${tx}px,${ty}px) rotateX(${rx}deg) rotateZ(${rz}deg) scale(${sc})`;
        one("[data-dots]").style.opacity = String(a * (1 - c) * 0.9);
        one("[data-dims]").style.opacity = String(ss(0.26, 0.34, p) * (1 - ss(0.56, 0.64, p)));
        const tilesOn = p <= 0.66;
        one("[data-tiles]").style.visibility = tilesOn ? "" : "hidden";
        if (tilesOn) {
          const front = ss(0.3, 0.54, p) * 20 - 3;
          const sink = 1 - ss(0.56, 0.64, p);
          all("[data-t]").forEach((tile, k) => {
            const col = k % 12;
            const row = (k / 12) | 0;
            const dd = front - (col + row * 0.55);
            const crest = Math.exp(-(((dd - 1.2) / 1.1) ** 2));
            const h = Math.max(1, (crest * 70 + (dd > 1.2 ? 8 + ((k * 7) % 5) : 2)) * sink * a);
            if (!tile._f) tile._f = ["[data-top]", "[data-fr]", "[data-rt]"].map((s) => tile.querySelector<HTMLElement>(s)!);
            tile.style.transform = `translateZ(${h}px)`;
            tile._f[1]!.style.transform = `rotateX(-90deg) scaleY(${h / 40})`;
            tile._f[2]!.style.transform = `rotateY(90deg) scaleX(${h / 40})`;
            const b = Math.round((dd > 1.2 ? 1 : crest) * 10) / 10;
            if (tile._b !== b) {
              tile._b = b;
              const r = Math.round(L(243, 31, b * 0.9));
              const gg = Math.round(L(245, 111, b * 0.9));
              const bb = Math.round(L(248, 229, b * 0.9));
              tile._f[0]!.style.background = `rgb(${r},${gg},${bb})`;
              tile._f[1]!.style.background = `rgb(${Math.round(r * 0.82)},${Math.round(gg * 0.85)},${Math.round(bb * 0.9)})`;
              tile._f[2]!.style.background = `rgb(${Math.round(r * 0.72)},${Math.round(gg * 0.76)},${Math.round(bb * 0.84)})`;
            }
          });
        }
        const pe = ss(0.56, 0.66, p);
        one("[data-panel]").style.transform = `translateZ(${(1 - pe) * -60 + 2}px)`;
        all("[data-pbg]").forEach((node) => (node.style.opacity = String(pe)));
        one("[data-pui]").style.opacity = String(ss(0.62, 0.7, p));
      }
      if (pc || (d > 0 && !reduced)) {
        all("[data-card]").forEach((card, j) => {
          const C = CARDS[j % CARDS.length]!;
          if (!card._s) {
            card.style.background = `linear-gradient(160deg,rgba(255,255,255,.35),rgba(255,255,255,0) 55%),rgb(${C.c.join(",")})`;
            card.style.color = C.ink;
            card._s = 1;
          }
          const e = ss(0.64 + j * 0.022, 0.76 + j * 0.022, p);
          const fl = (8 + Math.sin(t * 1.2 + j * 1.3) * 4) * d;
          card.style.opacity = e > 0.01 ? "1" : "0";
          card.style.transform = `translate3d(${(1 - e) * ((j % 3) - 1) * 120}px,${(1 - e) * -260}px,${(1 - e) * 700 + 6 + fl}px) rotateX(${(1 - e) * -40}deg) rotateZ(${(1 - e) * (j % 2 ? 24 : -18)}deg)`;
        });
      }
    };

    const loop = () => {
      tick(performance.now() / 1000);
      frame = window.requestAnimationFrame(loop);
    };
    frame = window.requestAnimationFrame(loop);
    return () => window.cancelAnimationFrame(frame);
  }, [storyRef, mouseX]);
}

export function LandingPage() {
  const router = useRouter();
  const storyRef = useRef<HTMLDivElement>(null);
  const mouseX = useRef<number | null>(null);
  const storedUser = useSyncExternalStore(subscribe, readUser, () => "");
  const [justSignedIn, setJustSignedIn] = useState<User | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showDemo, setShowDemo] = useState(false);
  useStoryAnimation(storyRef, mouseX);

  const signedInUser: User | null = justSignedIn ?? (storedUser ? (JSON.parse(storedUser) as User) : null);

  const goLogin = (e?: MouseEvent) => {
    e?.preventDefault();
    const el = document.getElementById("login");
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY, behavior: "smooth" });
  };

  const signIn = async (username: string) => {
    if (loading) return;
    setLoading(true);
    setError("");
    try {
      const session = await api.devLogin(username);
      storeSession(session);
      setJustSignedIn(session.user);
      window.setTimeout(() => router.push("/library"), 700);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 404 ? "No officer account matches that email." : `Can't reach GovSearch right now. ${err instanceof Error ? err.message : ""}`);
    } finally {
      setLoading(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const value = email.trim().toLowerCase();
    if (!/^[^\s@]+(@\S+\.\S+)?$/.test(value)) {
      setError("Enter your work email address.");
      return;
    }
    void signIn(value.split("@")[0]!);
  };

  const signOut = () => {
    clearSession();
    setJustSignedIn(null);
    setPassword("");
    window.location.href = "/";
  };

  const linkBtn = { background: "none", border: 0, padding: 0, font: "inherit", letterSpacing: "inherit", color: "var(--ink)", cursor: "pointer" } as const;
  const label = { fontSize: 10, fontWeight: 600, letterSpacing: ".04em", textTransform: "uppercase", color: "var(--ink-2)" } as const;

  return (
    <div style={{ background: "#DEE0E4", position: "relative" }}>
      <header
        style={{ position: "fixed", top: 0, left: 0, right: 0, zIndex: 30, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, padding: "20px 0 16px", margin: "0 clamp(20px,3vw,40px)", borderBottom: "1px solid rgba(21,23,28,.14)" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div style={{ fontWeight: 600, fontSize: 22, letterSpacing: "-.02em" }}>GOVSEARCH</div>
          <div style={{ fontSize: 10, lineHeight: 1.3, color: "var(--ink-2)", textTransform: "uppercase", letterSpacing: ".02em" }}>
            The fastest way to find
            <br />
            what your agency knows.
          </div>
        </div>
        <nav style={{ display: "flex", gap: "clamp(16px,3vw,44px)", fontSize: 11, letterSpacing: ".04em", textTransform: "uppercase", fontWeight: 500 }}>
          {NAV.map((n) => (
            <a key={n} href="#login" onClick={goLogin} style={{ color: "var(--ink)" }}>
              {n} ⌄
            </a>
          ))}
        </nav>
        <div style={{ display: "flex", alignItems: "center", gap: 22, fontSize: 11, letterSpacing: ".04em", textTransform: "uppercase", fontWeight: 500 }}>
          {signedInUser ? (
            <button className="link-btn" style={{ ...linkBtn, fontWeight: 600 }} onClick={() => router.push("/library")}>
              [ Open library ]
            </button>
          ) : (
            <>
              <button className="link-btn" style={linkBtn} onClick={() => goLogin()}>
                Sign in
              </button>
              <button className="link-btn" style={{ ...linkBtn, fontWeight: 600 }} onClick={() => goLogin()}>
                [ Request access ]
              </button>
            </>
          )}
        </div>
      </header>

      <div ref={storyRef} style={{ height: "640vh", position: "relative" }}>
        <div
          onMouseMove={(e) => (mouseX.current = e.clientX - window.innerWidth / 2)}
          onMouseLeave={() => (mouseX.current = null)}
          style={{ position: "sticky", top: 0, height: "100vh", overflow: "hidden", background: "radial-gradient(110% 80% at 50% 10%,#E9EAED 0%,#DCDEE2 60%,#CFD2D7 100%)" }}
        >
          <div
            data-sun="1"
            style={{ position: "absolute", inset: "-20%", opacity: 0, pointerEvents: "none", background: "repeating-linear-gradient(118deg,rgba(255,252,244,0) 0px,rgba(255,252,244,.6) 120px,rgba(255,252,244,.7) 200px,rgba(255,252,244,.6) 240px,rgba(160,165,175,.12) 320px,rgba(255,252,244,0) 440px)" }}
          />
          <div data-idx="1" style={{ position: "absolute", top: 84, left: "clamp(20px,3vw,40px)", fontSize: 10, fontWeight: 600, letterSpacing: ".04em", zIndex: 5 }}>
            001 — 004
          </div>

          <div data-hero="1" style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 5 }}>
            <div style={{ position: "absolute", top: 112, left: "clamp(20px,3vw,40px)", display: "flex", flexDirection: "column", gap: 22 }}>
              <h1 style={{ margin: 0, fontWeight: 400, fontSize: "clamp(28px,2.9vw,42px)", lineHeight: 1.08, letterSpacing: "-.01em", textTransform: "uppercase", maxWidth: "15ch" }}>
                Your agency&apos;s memory, searchable in seconds.
              </h1>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 9, fontWeight: 600, letterSpacing: ".04em", textTransform: "uppercase" }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--blue)" }} />
                Pilot now open for Sarawak agencies
              </div>
            </div>
            <p style={{ position: "absolute", top: 110, right: "clamp(20px,3vw,40px)", margin: 0, maxWidth: 300, fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>
              Policies, SOPs, circulars and minutes in one place. Ask a question, get the answer with the page it came from.
            </p>
            <div style={{ position: "absolute", left: 0, right: 0, bottom: 72, display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)", textAlign: "center" }}>
                Ready to stop searching
                <br />
                and start deciding?
              </p>
              <button className="pill pill-primary" style={{ pointerEvents: "auto", padding: "12px 30px" }} onClick={() => goLogin()}>
                Sign in
              </button>
            </div>
          </div>

          <div style={{ position: "absolute", bottom: 28, left: "clamp(20px,3vw,40px)", display: "flex", gap: 16, alignItems: "center", fontSize: 9, fontWeight: 600, letterSpacing: ".04em", textTransform: "uppercase", zIndex: 5 }}>
            <span style={{ fontSize: 14 }}>↓</span>
            <span data-scrolllabel="1">Discover more</span>
          </div>

          <div style={{ position: "absolute", inset: 0, perspective: 1800, perspectiveOrigin: "50% 45%" }}>
            <div data-ribbon="1" style={{ position: "absolute", left: "50%", top: "57%", width: 0, height: 0, transformStyle: "preserve-3d" }}>
              {Array.from({ length: RIBBON }, (_, i) => (
                <div key={i} data-r="1" style={{ position: "absolute", left: -48, top: -75, width: 96, height: 150, willChange: "transform" }}>
                  <div data-c="1" style={{ position: "absolute", left: 0, top: -10, width: 40, height: 14, borderRadius: "7px 7px 0 0" }} />
                  <div data-c="1" style={{ position: "absolute", inset: 0, borderRadius: "3px 10px 10px 10px", border: "1px solid rgba(255,255,255,.7)" }} />
                </div>
              ))}
              {NUMS.map((n, i) => (
                <div key={i} data-n="1" className="mono" style={{ position: "absolute", fontSize: 8, color: "var(--ink-3)", whiteSpace: "nowrap", opacity: 0 }}>
                  {n}
                </div>
              ))}
            </div>

            <div data-cam="1" style={{ position: "absolute", left: "50%", top: "52%", width: 0, height: 0, transformStyle: "preserve-3d", visibility: "hidden" }}>
              <div style={{ position: "absolute", left: -450, top: -300, width: 900, height: 600, transformStyle: "preserve-3d" }}>
                <div data-dots="1" style={{ position: "absolute", inset: "-180px -220px", backgroundImage: "radial-gradient(rgba(21,23,28,.4) 1.3px,transparent 1.8px)", backgroundSize: "30px 30px", opacity: 0 }} />
                <div data-dims="1" className="mono" style={{ position: "absolute", inset: -50, opacity: 0, fontSize: 10, color: "var(--ink-2)" }}>
                  <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 1, background: "rgba(21,23,28,.45)" }} />
                  <div style={{ position: "absolute", top: 0, bottom: 0, left: 0, width: 1, background: "rgba(21,23,28,.45)" }} />
                  <div style={{ position: "absolute", top: -20, left: "50%" }}>12,408</div>
                  <div style={{ position: "absolute", left: -44, top: "50%" }}>6 types</div>
                  <div style={{ position: "absolute", right: 0, bottom: -24 }}>+214 / night</div>
                </div>
                <div data-tiles="1" style={{ position: "absolute", left: 150, top: 100, width: 600, height: 400, display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 4, transformStyle: "preserve-3d" }}>
                  {Array.from({ length: TILES }, (_, i) => (
                    <div key={i} data-t="1" style={{ position: "relative", transformStyle: "preserve-3d" }}>
                      <div data-top="1" style={{ position: "absolute", inset: 0, borderRadius: 3, background: "#F3F5F8" }} />
                      <div data-fr="1" style={{ position: "absolute", left: 0, top: "100%", width: "100%", height: 40, transformOrigin: "top", background: "#C9CFD8" }} />
                      <div data-rt="1" style={{ position: "absolute", left: "100%", top: 0, width: 40, height: "100%", transformOrigin: "left", background: "#B7BEC9" }} />
                    </div>
                  ))}
                </div>

                <div data-panel="1" style={{ position: "absolute", inset: 0, transformStyle: "preserve-3d" }}>
                  <div data-pbg="1" style={{ position: "absolute", inset: -26, borderRadius: 44, border: "1.5px solid rgba(255,255,255,.9)", background: "rgba(232,235,240,.55)", boxShadow: "0 40px 80px rgba(40,50,70,.18)", opacity: 0 }} />
                  <div data-pbg="1" style={{ position: "absolute", inset: 0, borderRadius: 30, background: "linear-gradient(150deg,#F7F8FA,#E6E9EE)", boxShadow: "inset 0 1px 0 #fff", opacity: 0 }} />
                  <div data-pui="1" style={{ position: "absolute", inset: 0, padding: 28, display: "grid", gridTemplateColumns: "190px 1fr", gap: 28, opacity: 0 }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <div style={{ fontWeight: 600, fontSize: 17, marginBottom: 22 }}>Library</div>
                      {[
                        ["All documents", "12,408"],
                        ["Policies", "1,204"],
                        ["SOPs", "3,118"],
                        ["Circulars", "2,876"],
                        ["Guidelines", "942"],
                        ["Reports", "2,511"],
                        ["Minutes", "1,757"],
                      ].map(([name, count], i) => (
                        <div key={name} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "8px 10px", borderRadius: 8, background: i === 0 ? "#fff" : undefined }}>
                          <span>{name}</span>
                          <span className="mono" style={{ fontSize: 10, color: "var(--ink-3)" }}>
                            {count}
                          </span>
                        </div>
                      ))}
                      <div style={{ marginTop: "auto", display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ width: 30, height: 30, borderRadius: "50%", background: "#C9D6EA" }} />
                        <span style={{ fontSize: 11, lineHeight: 1.3 }}>
                          <b style={{ fontWeight: 600 }}>Nur Aisyah</b>
                          <br />
                          <span style={{ color: "var(--ink-3)" }}>Policy Officer</span>
                        </span>
                      </div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontWeight: 600, fontSize: 22 }}>Ask GovSearch</span>
                        <span className="mono" style={{ fontSize: 10, color: "var(--ink-3)" }}>
                          0.8s · 3 sources
                        </span>
                      </div>
                      <div style={{ background: "#fff", borderRadius: 999, padding: "12px 18px", fontSize: 13, color: "var(--ink-2)", boxShadow: "0 2px 8px rgba(20,30,60,.06)" }}>How many days a week can staff work from home?</div>
                      <div style={{ background: "#fff", borderRadius: 16, padding: "16px 18px", fontSize: 13, lineHeight: 1.5 }}>
                        <div className="mono" style={{ fontSize: 9, letterSpacing: ".06em", color: "var(--blue)", marginBottom: 6 }}>
                          ANSWER
                        </div>
                        Up to three days a week under Circular PKP/HR/2026/03, which replaces the two-day limit of the 2024 circular.
                      </div>
                    </div>
                  </div>
                  <div style={{ position: "absolute", left: 246, top: 248, width: 626, height: 330, display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 12, transformStyle: "preserve-3d" }}>
                    {CARDS.map((c) => (
                      <div key={c.title} data-card="1" style={{ height: 150, borderRadius: 14, padding: 14, display: "flex", flexDirection: "column", justifyContent: "space-between", opacity: 0, boxShadow: "0 14px 28px rgba(20,40,90,.22)" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <span className="mono" style={{ fontSize: 9, letterSpacing: ".06em", padding: "3px 7px", borderRadius: 999, background: "rgba(255,255,255,.22)" }}>
                            {c.type}
                          </span>
                          <span className="mono" style={{ fontSize: 9 }}>
                            {c.match}
                          </span>
                        </div>
                        <div style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.3 }}>{c.title}</div>
                        <div className="mono" style={{ fontSize: 9, opacity: 0.85 }}>
                          {c.ref}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div data-t2="1" style={{ position: "absolute", left: "clamp(20px,3vw,40px)", bottom: 90, maxWidth: 340, opacity: 0, zIndex: 5, pointerEvents: "none" }}>
            <h2 style={{ margin: "0 0 12px", fontWeight: 400, fontSize: "clamp(22px,2.2vw,32px)", lineHeight: 1.1, textTransform: "uppercase" }}>Your whole archive, indexed.</h2>
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5, color: "var(--ink-2)" }}>
              Every policy, SOP, circular and set of minutes is read, linked and kept current — scanned pages, Malay and Chinese included.
            </p>
          </div>

          <div data-t3="1" style={{ position: "absolute", left: "clamp(20px,3vw,40px)", top: "50%", transform: "translateY(-50%)", maxWidth: 380, opacity: 0, zIndex: 5 }}>
            <h2 style={{ margin: "0 0 20px", fontWeight: 400, fontSize: "clamp(24px,2.5vw,36px)", lineHeight: 1.1, textTransform: "uppercase" }}>Ask once. Get the cited answer.</h2>
            <p style={{ margin: "0 0 56px", fontSize: 13, lineHeight: 1.55, color: "var(--ink-2)", maxWidth: 300 }}>
              Skip the folder hunt. GovSearch answers in plain language and links the exact circular, section and page, so you can verify before you act.
            </p>
            <div className="caps" style={{ marginBottom: 14 }}>
              Find faster, decide better.
            </div>
            <button className="pill pill-ghost" style={{ padding: "10px 26px", fontSize: 9 }} onClick={() => goLogin()}>
              Sign in
            </button>
          </div>
        </div>
      </div>

      <section
        id="login"
        style={{ minHeight: "100vh", position: "relative", display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,440px)", gap: 48, alignItems: "center", padding: "120px clamp(20px,6vw,96px) 60px", background: "radial-gradient(90% 70% at 70% 40%,#ECEEF1 0%,#DEE0E4 70%)", overflow: "hidden" }}
      >
        <div style={{ position: "absolute", inset: 0, backgroundImage: "radial-gradient(rgba(21,23,28,.18) 1.2px,transparent 1.6px)", backgroundSize: "30px 30px", pointerEvents: "none" }} />
        <div style={{ position: "relative" }}>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: ".04em", marginBottom: 24 }}>004 — 004</div>
          <h2 style={{ margin: "0 0 20px", fontWeight: 400, fontSize: "clamp(30px,3.6vw,52px)", lineHeight: 1.04, textTransform: "uppercase", maxWidth: "12ch" }}>Sign in to your library.</h2>
          <p style={{ margin: 0, maxWidth: 340, fontSize: 14, lineHeight: 1.55, color: "var(--ink-2)" }}>
            Use your agency account. Results only include documents your role is cleared to see.
          </p>
        </div>

        <div style={{ position: "relative", background: "rgba(248,249,251,.78)", backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)", border: "1.5px solid rgba(255,255,255,.95)", borderRadius: 28, padding: 36, boxShadow: "0 40px 80px rgba(40,50,70,.14)" }}>
          {!signedInUser ? (
            <div>
              <button
                type="button"
                onClick={() => setShowDemo(!showDemo)}
                style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 10, border: "1px solid rgba(21,23,28,.16)", background: "#fff", borderRadius: 999, padding: 14, font: "inherit", fontSize: 13, color: "var(--ink)", cursor: "pointer" }}
              >
                <span style={{ width: 16, height: 16, borderRadius: 4, background: "var(--blue)" }} />
                Continue with agency SSO
              </button>
              {showDemo && (
                <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
                  <span className="mono" style={{ fontSize: 10, color: "var(--ink-3)" }}>
                    PILOT DIRECTORY · choose an officer
                  </span>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {DEMO.map((u) => (
                      <button key={u} type="button" className="pill pill-ghost" style={{ padding: "8px 14px" }} disabled={loading} onClick={() => void signIn(u)}>
                        {u}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="mono" style={{ display: "flex", alignItems: "center", gap: 12, margin: "22px 0", fontSize: 10, color: "var(--ink-4)" }}>
                <span style={{ flex: 1, height: 1, background: "rgba(21,23,28,.12)" }} />
                OR
                <span style={{ flex: 1, height: 1, background: "rgba(21,23,28,.12)" }} />
              </div>
              <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <span style={label}>Work email</span>
                  <input
                    className="text-input"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      setError("");
                    }}
                    type="text"
                    autoComplete="username"
                    placeholder="alice@jpdn.sarawak.gov.my"
                  />
                </label>
                <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <span style={{ ...label, display: "flex", justifyContent: "space-between" }}>
                    Password
                    <a href="#login" onClick={(e) => e.preventDefault()} style={{ color: "var(--blue)" }}>
                      Forgot?
                    </a>
                  </span>
                  <div style={{ position: "relative", display: "flex" }}>
                    <input
                      className="text-input"
                      style={{ flex: 1, minWidth: 0, paddingRight: 64 }}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      type={showPw ? "text" : "password"}
                      autoComplete="current-password"
                      placeholder="••••••••"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPw(!showPw)}
                      style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", background: "none", border: 0, fontSize: 10, fontWeight: 600, letterSpacing: ".04em", textTransform: "uppercase", color: "var(--ink-3)", cursor: "pointer" }}
                    >
                      {showPw ? "Hide" : "Show"}
                    </button>
                  </div>
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "var(--ink-2)", cursor: "pointer" }}>
                  <input type="checkbox" checked={remember} onChange={() => setRemember(!remember)} style={{ accentColor: "var(--blue)", width: 16, height: 16, margin: 0 }} />
                  Trust this device for 30 days
                </label>
                {error && <div style={{ fontSize: 13, color: "var(--red)" }}>{error}</div>}
                <button type="submit" className="pill pill-primary" style={{ marginTop: 4, padding: 15, fontSize: 11, display: "flex", justifyContent: "center", alignItems: "center", gap: 10 }} disabled={loading}>
                  {loading && <span style={{ width: 12, height: 12, borderRadius: "50%", border: "2px solid rgba(255,255,255,.4)", borderTopColor: "#fff", animation: "spin .8s linear infinite" }} />}
                  {loading ? "Signing in" : "Sign in"}
                </button>
              </form>
              <p style={{ margin: "22px 0 0", fontSize: 13, color: "var(--ink-3)" }}>
                New agency?{" "}
                <a href="#login" onClick={(e) => e.preventDefault()}>
                  Request pilot access
                </a>
              </p>
            </div>
          ) : (
            <div style={{ padding: "20px 0" }}>
              <div className="caps" style={{ color: "var(--blue)", marginBottom: 14 }}>
                ● Signed in
              </div>
              <h3 style={{ margin: "0 0 10px", fontWeight: 400, fontSize: 30, textTransform: "uppercase" }}>Welcome back</h3>
              <p style={{ margin: "0 0 24px", fontSize: 14, lineHeight: 1.5, color: "var(--ink-2)" }}>
                {signedInUser.display_name} · {signedInUser.departments.filter((d) => d.id !== "public").map((d) => d.name).join(", ") || "Agency"}. Opening your library…
              </p>
              <button className="pill pill-primary" style={{ marginRight: 20, padding: "12px 24px" }} onClick={() => router.push("/library")}>
                Open library →
              </button>
              <button className="link-btn caps" style={{ fontSize: 11 }} onClick={signOut}>
                [ Sign out ]
              </button>
            </div>
          )}
          <div className="mono" style={{ marginTop: 22, fontSize: 10, lineHeight: 1.5, color: "var(--ink-4)" }}>
            Authorised users only. Activity is logged per agency policy.
            <br />
            Pilot build: sign in with an officer email (e.g. alice@…, ben@…, chloe@…, admin@…); passwords are not yet verified.
          </div>
        </div>
      </section>
    </div>
  );
}
