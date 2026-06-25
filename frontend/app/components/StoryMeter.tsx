"use client";

import React from "react";

export interface StoryHeat {
  heat: number;
  stage?: number;
  level: number;
  label: string;
  max_heat: number;
  climax?: boolean;
  explicit?: boolean;
}

interface Props {
  heat?: StoryHeat | null;
  compact?: boolean;
}

// Geometry for a 180° gauge.
const CX = 120;
const CY = 116;
const R = 92;
const TAU = Math.PI / 180;

// 0° = right, 90° = top, 180° = left.
function polar(angleDeg: number, radius: number) {
  const a = angleDeg * TAU;
  return { x: CX + radius * Math.cos(a), y: CY - radius * Math.sin(a) };
}

// Arc from a1 to a2 (a1 > a2) along the top of the circle.
function arcPath(a1: number, a2: number, radius: number) {
  const p1 = polar(a1, radius);
  const p2 = polar(a2, radius);
  return `M ${p1.x} ${p1.y} A ${radius} ${radius} 0 0 1 ${p2.x} ${p2.y}`;
}

const ZONES = [
  { label: "Angry", color: "#f87171", a1: 180, a2: 120 },
  { label: "Flirty", color: "#f472b6", a1: 120, a2: 60 },
  { label: "Hot", color: "#e879f9", a1: 60, a2: 0 },
];

export default function StoryMeter({ heat, compact }: Props) {
  const max = heat?.max_heat ?? 15;
  const value = Math.max(0, Math.min(max, heat?.heat ?? 0));
  const label = heat?.label ?? "Angry";
  const level = heat?.level ?? 1;
  const climax = !!heat?.climax;
  const totalPhases = max + 1;
  const phase = heat?.stage ?? value + 1;

  const f = max > 0 ? value / max : 0;
  const needleAngle = 180 - f * 180;
  const tip = polar(needleAngle, R - 10);

  // 15 step ticks (16 boundaries).
  const ticks = Array.from({ length: max + 1 }, (_, i) => {
    const tf = i / max;
    const ang = 180 - tf * 180;
    const inner = polar(ang, R - 14);
    const outer = polar(ang, R - 4);
    const reached = i <= value;
    return { inner, outer, reached, key: i };
  });

  if (compact) {
    // Small inline gauge under her name: a continuous cold→hot gradient arc
    // (blue → yellow → red), no discrete levels and no level-name label.
    const ccx = 48;
    const ccy = 42;
    const cr = 36;
    const cpolar = (deg: number, radius: number) => {
      const a = deg * TAU;
      return { x: ccx + radius * Math.cos(a), y: ccy - radius * Math.sin(a) };
    };
    const carc = (a1: number, a2: number, radius: number) => {
      const p1 = cpolar(a1, radius);
      const p2 = cpolar(a2, radius);
      return `M ${p1.x} ${p1.y} A ${radius} ${radius} 0 0 1 ${p2.x} ${p2.y}`;
    };
    const ctip = cpolar(needleAngle, cr - 5);
    return (
      <div className="flex flex-col select-none" style={{ width: 96 }}>
        <svg width={96} height={50} viewBox="0 0 96 50">
          <defs>
            <linearGradient
              id="heatGauge"
              x1={ccx - cr}
              y1="0"
              x2={ccx + cr}
              y2="0"
              gradientUnits="userSpaceOnUse"
            >
              <stop offset="0%" stopColor="#3b82f6" />
              <stop offset="50%" stopColor="#facc15" />
              <stop offset="100%" stopColor="#ef4444" />
            </linearGradient>
          </defs>
          <path
            d={carc(180, 0, cr)}
            fill="none"
            stroke="url(#heatGauge)"
            strokeWidth={6}
            strokeLinecap="round"
          />
          <line
            x1={ccx}
            y1={ccy}
            x2={ctip.x}
            y2={ctip.y}
            stroke="#ffffff"
            strokeWidth={2}
            strokeLinecap="round"
            style={{ transition: "all 0.6s cubic-bezier(0.34, 1.56, 0.64, 1)" }}
          />
          <circle cx={ccx} cy={ccy} r={3} fill="#ffffff" />
        </svg>
        <div className="flex justify-between -mt-1.5 text-[8px] uppercase tracking-widest text-[var(--muted)]">
          <span>Cold</span>
          <span>Hot</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center pt-3 pb-2 select-none">
      <svg width={240} height={140} viewBox="0 0 240 140">
        {/* Track */}
        <path
          d={arcPath(180, 0, R)}
          fill="none"
          stroke="#2a2a3c"
          strokeWidth={14}
          strokeLinecap="round"
        />
        {/* Colored zones */}
        {ZONES.map((z, i) => {
          const active = level === i + 1;
          return (
            <path
              key={z.label}
              d={arcPath(z.a1, z.a2, R)}
              fill="none"
              stroke={z.color}
              strokeWidth={active ? 14 : 11}
              strokeLinecap="butt"
              opacity={active ? 1 : 0.35}
            />
          );
        })}
        {/* Step ticks */}
        {ticks.map((t) => (
          <line
            key={t.key}
            x1={t.inner.x}
            y1={t.inner.y}
            x2={t.outer.x}
            y2={t.outer.y}
            stroke={t.reached ? "#ffffff" : "#ffffff"}
            strokeOpacity={t.reached ? 0.9 : 0.18}
            strokeWidth={1.5}
          />
        ))}
        {/* Needle */}
        <line
          x1={CX}
          y1={CY}
          x2={tip.x}
          y2={tip.y}
          stroke={climax ? "#e879f9" : "#ffffff"}
          strokeWidth={3}
          strokeLinecap="round"
          style={{ transition: "all 0.6s cubic-bezier(0.34, 1.56, 0.64, 1)" }}
        />
        <circle cx={CX} cy={CY} r={7} fill="#ffffff" />
        <circle cx={CX} cy={CY} r={3.5} fill="#1a1a2e" />
      </svg>

      {/* Label */}
      <div className="-mt-3 flex flex-col items-center gap-0.5">
        <span
          className="text-[15px] font-bold tracking-wide uppercase"
          style={{ color: ZONES[level - 1]?.color ?? "#f87171" }}
        >
          {climax ? "Climax" : label}
        </span>
        <span className="text-[10px] text-[var(--muted)] uppercase tracking-widest">
          Phase {phase} / {totalPhases}
        </span>
      </div>
    </div>
  );
}
