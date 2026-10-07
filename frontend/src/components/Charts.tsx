// Lightweight SVG line charts fed ONLY by real backtest series (equity/drawdown).
// No demo/simulated data is ever rendered.
import type { EquityPoint } from "../api/client";

function path(pts: { x: number; y: number }[]): string {
    return pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
}

function Chart({ data, pick, color, height = 180 }: {
    data: EquityPoint[]; pick: (p: EquityPoint) => number; color: string; height?: number;
}) {
    if (!data.length) return <p className="muted">No data.</p>;
    const W = 720, H = height, pad = 8;
    const vals = data.map(pick);
    const min = Math.min(...vals), max = Math.max(...vals);
    const span = max - min || 1;
    const pts = data.map((p, i) => ({
        x: pad + (i / Math.max(1, data.length - 1)) * (W - 2 * pad),
        y: H - pad - ((pick(p) - min) / span) * (H - 2 * pad),
    }));
    return (
        <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img">
            <path d={path(pts)} fill="none" stroke={color} strokeWidth="1.6" />
            <text x={pad} y={pad + 8} className="axis">{max.toFixed(0)}</text>
            <text x={pad} y={H - 2} className="axis">{min.toFixed(0)}</text>
        </svg>
    );
}

export function EquityChart({ data }: { data: EquityPoint[] }) {
    return <Chart data={data} pick={(p) => p.equity} color="#58a6ff" />;
}
export function DrawdownChart({ data }: { data: EquityPoint[] }) {
    return <Chart data={data} pick={(p) => -p.drawdown} color="#f85149" height={120} />;
}
