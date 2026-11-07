// A small trend line drawn as plain SVG, so lists can show one per row without
// loading ECharts. It is one neutral colour: the shape shows the trend, and
// any change figure next to it comes from the backend. Points without a value
// break the line instead of dropping to zero.
import { cn } from "@/lib/utils";

export interface TrendPoint {
  date: string;
  value: number | null;
}

/** `label` describes the line for screen readers; leave it out when the row around it already says everything. */
export function Sparkline({
  points,
  label,
  className,
}: {
  points: TrendPoint[];
  label?: string;
  className?: string;
}) {
  const values = points
    .map((point) => point.value)
    .filter(
      (value): value is number =>
        typeof value === "number" && Number.isFinite(value),
    );
  if (points.length < 2 || values.length < 2) return null;
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const step = 100 / (points.length - 1);
  // Split into runs of consecutive known values.
  const runs: string[] = [];
  let run: string[] = [];
  points.forEach((point, index) => {
    if (typeof point.value === "number" && Number.isFinite(point.value)) {
      run.push(
        `${(index * step).toFixed(2)},${(22 - ((point.value - low) / span) * 20).toFixed(2)}`,
      );
    } else if (run.length) {
      runs.push(run.join(" "));
      run = [];
    }
  });
  if (run.length) runs.push(run.join(" "));
  return (
    <svg
      viewBox="0 0 100 24"
      preserveAspectRatio="none"
      {...(label
        ? { role: "img", "aria-label": label }
        : { "aria-hidden": true })}
      className={cn("h-8 w-full text-chart-1", className)}
    >
      {runs.map((line, index) =>
        line.includes(" ") ? (
          <polyline
            key={index}
            points={line}
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
            strokeLinejoin="round"
          />
        ) : null,
      )}
    </svg>
  );
}
