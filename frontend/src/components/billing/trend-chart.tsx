"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { pkr, pkrExact } from "@/lib/types/billing";
import { cn } from "@/lib/utils";

/**
 * Net sales and gross profit over time.
 *
 * Both series are money in the same currency, so they share one axis — a
 * second y-scale would let any shape be drawn and is never used here.
 * Both series wear the brand teal. Two steps of one hue are too close to
 * tell apart by colour (ΔE 10 against a floor of 15), so gross profit is
 * dashed and the legend shows the dash — identity never rests on colour.
 */
export interface TrendPoint {
  bucket: string;
  net_sales: string;
  gross_profit: string;
}

const H = 240;
// Below this the end-of-line value labels are dropped and the figures move
// into the legend, where they have room to be read.
const NARROW = 420;

const SERIES = [
  { key: "net_sales", label: "Net sales", color: "var(--chart-1)", dash: undefined },
  { key: "gross_profit", label: "Gross profit", color: "var(--chart-3)", dash: "6 4" },
] as const;

export function TrendChart({
  points,
  bucket,
}: {
  points: TrendPoint[];
  bucket: "day" | "month";
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  // The viewBox tracks the real rendered width, so 11px text is 11px on a
  // phone instead of being scaled down to something unreadable.
  const [width, setWidth] = useState(720);

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width;
      if (w > 0) setWidth(Math.round(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [showTable]);

  const narrow = width < NARROW;
  const W = Math.max(280, width);
  const PAD = useMemo(
    () => ({ top: 16, right: narrow ? 10 : 76, bottom: 28, left: 8 }),
    [narrow],
  );

  const model = useMemo(() => {
    const values = points.flatMap((p) => [Number(p.net_sales), Number(p.gross_profit)]);
    const max = Math.max(1, ...values);
    const min = Math.min(0, ...values);
    const span = max - min || 1;
    const innerW = W - PAD.left - PAD.right;
    const innerH = H - PAD.top - PAD.bottom;
    const x = (i: number) =>
      PAD.left + (points.length <= 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
    const y = (v: number) => PAD.top + innerH - ((v - min) / span) * innerH;
    return { max, min, x, y, innerH };
  }, [points, W, PAD]);

  if (points.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        No invoices in this period yet.
      </p>
    );
  }

  function path(key: "net_sales" | "gross_profit") {
    return points
      .map((p, i) => `${i === 0 ? "M" : "L"}${model.x(i)},${model.y(Number(p[key]))}`)
      .join(" ");
  }

  function label(iso: string) {
    const d = new Date(iso);
    return bucket === "day"
      ? d.toLocaleDateString("en-PK", { day: "numeric", month: "short" })
      : d.toLocaleDateString("en-PK", { month: "short", year: "2-digit" });
  }

  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const px = ((e.clientX - rect.left) / rect.width) * W;
    let nearest = 0;
    let best = Infinity;
    points.forEach((_, i) => {
      const d = Math.abs(model.x(i) - px);
      if (d < best) {
        best = d;
        nearest = i;
      }
    });
    setHover(nearest);
  }

  const active = hover != null ? points[hover] : null;
  const last = points.length - 1;

  return (
    <figure className="m-0 space-y-2">
      <figcaption className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex flex-wrap gap-4 text-xs">
          {SERIES.map((s) => (
            <span key={s.key} className="flex items-center gap-1.5 text-muted-foreground">
              {s.dash ? (
                <svg aria-hidden width="18" height="8" className="inline-block">
                  <line x1="0" y1="4" x2="18" y2="4" stroke={s.color}
                    strokeWidth="2" strokeDasharray="4 3" />
                </svg>
              ) : (
                <span
                  aria-hidden
                  className="inline-block h-2 w-4 rounded-sm"
                  style={{ background: s.color }}
                />
              )}
              {s.label}
              {narrow && points.length > 0 && (
                <strong className="text-foreground tabular-nums">
                  {pkr(points[points.length - 1][s.key])}
                </strong>
              )}
            </span>
          ))}
        </span>
        <button
          type="button"
          className="text-xs text-primary hover:underline"
          onClick={() => setShowTable((v) => !v)}
        >
          {showTable ? "Show chart" : "Show as table"}
        </button>
      </figcaption>

      {showTable ? (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="p-2 text-left">Period</th>
                <th className="p-2 text-right">Net sales</th>
                <th className="p-2 text-right">Gross profit</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.bucket} className="border-t border-border">
                  <td className="p-2">{label(p.bucket)}</td>
                  <td className="p-2 text-right tabular-nums">{pkrExact(p.net_sales)}</td>
                  <td className="p-2 text-right tabular-nums">{pkrExact(p.gross_profit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="relative" ref={wrapRef}>
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            className="h-56 w-full"
            role="img"
            aria-label={`Net sales and gross profit by ${bucket}`}
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
          >
            {/* recessive baseline + top gridline */}
            {[0, 0.5, 1].map((t) => {
              const yy = PAD.top + model.innerH * t;
              return (
                <line
                  key={t}
                  x1={PAD.left} x2={W - PAD.right} y1={yy} y2={yy}
                  stroke="currentColor"
                  className="text-border"
                  strokeWidth={1}
                />
              );
            })}

            {hover != null && (
              <line
                x1={model.x(hover)} x2={model.x(hover)}
                y1={PAD.top} y2={PAD.top + model.innerH}
                stroke="currentColor" className="text-muted-foreground/40"
                strokeWidth={1} strokeDasharray="3 3"
              />
            )}

            {SERIES.map((s) => (
              <path
                key={s.key}
                d={path(s.key)}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeDasharray={s.dash}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}

            {/* A single period draws no line segment, so mark the points
                themselves — otherwise a "Today" range looks like no data. */}
            {points.length === 1 &&
              SERIES.map((s) => (
                <circle
                  key={`solo-${s.key}`}
                  cx={model.x(0)}
                  cy={model.y(Number(points[0][s.key]))}
                  r={5}
                  fill={s.color}
                  stroke="var(--card)"
                  strokeWidth={2}
                />
              ))}

            {/* hovered markers, ringed against the surface so they stay legible */}
            {hover != null &&
              SERIES.map((s) => (
                <circle
                  key={s.key}
                  cx={model.x(hover)}
                  cy={model.y(Number(points[hover][s.key]))}
                  r={5}
                  fill={s.color}
                  stroke="var(--card)"
                  strokeWidth={2}
                />
              ))}

            {/* direct labels at the final point: two series, so no number on every
                point. Dropped when narrow — the legend shows them instead. */}
            {!narrow && SERIES.map((s) => (
              <text
                key={s.key}
                x={W - PAD.right + 8}
                y={model.y(Number(points[last][s.key])) + 4}
                className="fill-muted-foreground text-[11px]"
              >
                {pkr(points[last][s.key])}
              </text>
            ))}

            <text x={PAD.left} y={H - 8} className="fill-muted-foreground text-[11px]">
              {label(points[0].bucket)}
            </text>
            {points.length > 1 && (
              <text
                x={W - PAD.right} y={H - 8} textAnchor="end"
                className="fill-muted-foreground text-[11px]"
              >
                {label(points[last].bucket)}
              </text>
            )}
          </svg>

          {active && (
            <div
              className="pointer-events-none absolute top-2 rounded-lg border border-border bg-popover px-3 py-2 text-xs shadow-md"
              style={{
                left: `${Math.min((model.x(hover!) / W) * 100, 72)}%`,
              }}
            >
              <p className="font-medium">{label(active.bucket)}</p>
              {SERIES.map((s) => (
                <p key={s.key} className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className={cn("inline-block h-2 w-2", s.dash ? "rounded-none" : "rounded-full")}
                    style={{ background: s.color }}
                  />
                  <span className="text-muted-foreground">{s.label}</span>
                  <span className="ml-auto tabular-nums">{pkrExact(active[s.key])}</span>
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
