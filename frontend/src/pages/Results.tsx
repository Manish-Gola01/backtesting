import { useEffect, useState } from "react";
import { api, type Metrics, type ReadinessReport, type Trade } from "../api/client";
import { EquityChart, DrawdownChart } from "../components/Charts";

function fmt(v: any, dp = 2) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "number") return Number.isFinite(v) ? v.toFixed(dp) : "∞";
    return String(v);
}

const KPI: [string, keyof Metrics, number?][] = [
    ["Net Profit", "net_profit"], ["Net Profit %", "net_profit_pct"], ["Win Rate %", "win_rate"],
    ["Total Trades", "total_trades", 0], ["Profit Factor", "profit_factor"], ["Expectancy", "expectancy"],
    ["Max DD %", "max_drawdown_pct"], ["Sharpe", "sharpe_ratio"], ["Sortino", "sortino_ratio"],
    ["Avg Win", "avg_winning_trade"], ["Avg Loss", "avg_losing_trade"], ["Avg Hold (s)", "avg_holding_seconds", 0],
];

export default function Results({ id }: { id: string | null }) {
    const [metrics, setMetrics] = useState<Metrics | null>(null);
    const [trades, setTrades] = useState<Trade[]>([]);
    const [equity, setEquity] = useState<any[]>([]);
    const [monthly, setMonthly] = useState<Record<string, number>>({});
    const [readiness, setReadiness] = useState<ReadinessReport | null>(null);
    const [err, setErr] = useState<string | null>(null);
    const [filter, setFilter] = useState("");

    useEffect(() => {
        if (!id) return;
        Promise.all([api.metrics(id), api.trades(id), api.equity(id), api.monthly(id), api.readiness(id)])
            .then(([m, t, e, mo, r]) => { setMetrics(m.metrics); setTrades(t); setEquity(e); setMonthly(mo.monthly_returns); setReadiness(r); })
            .catch((e) => setErr(e.message));
    }, [id]);

    if (!id) return <section><h2>Results</h2><p className="muted">Run a backtest to see results.</p></section>;
    if (err) return <section><h2>Results</h2><p className="error">{err}</p></section>;
    if (!metrics) return <section><h2>Results</h2><p className="muted">Loading…</p></section>;

    const shown = trades.filter((t) => !filter || t.exit_reason.includes(filter.toUpperCase()) || t.side.includes(filter.toUpperCase()));

    return (
        <section>
            <h2>Results</h2>
            <div className="kpis">
                {KPI.map(([label, key, dp]) => (
                    <div className="kpi" key={key as string}>
                        <div className="kpi-label">{label}</div>
                        <div className="kpi-val">{fmt(metrics[key], dp)}</div>
                    </div>
                ))}
            </div>

            {readiness && (
                <div className={`readiness v-${readiness.verdict.replace(/\s+/g, "-").toLowerCase()}`}>
                    <div className="readiness-head">
                        <h3 className="sub" style={{ margin: 0 }}>Live Trading Readiness</h3>
                        <span className="verdict">{readiness.verdict}</span>
                        <span className="score">{readiness.readiness_score}/100 · {readiness.checks_passed}/{readiness.checks_total} checks</span>
                    </div>
                    <p className="verdict-note">{readiness.verdict_note}</p>

                    {/* Dedicated Current Proof of Profitability card */}
                    <div className="profitability-card">
                        <div className="profitability-header">
                            <span className="profitability-title">
                                <span>📊</span> Current Proof of Profitability
                            </span>
                            <div className="profitability-badges">
                                <span className={`badge-pop ${readiness.current_proof_of_profitability?.has_empirical_edge ? "status-historical" : "status-noedge"}`}>
                                    {readiness.current_proof_of_profitability?.has_empirical_edge ? "Historical Edge Observed" : "No Empirical Edge"}
                                </span>
                                <span className="badge-pop status-pending">
                                    Live Proof: Pending Paper Trading
                                </span>
                            </div>
                        </div>
                        <p className="profitability-summary">
                            {readiness.current_proof_of_profitability?.summary ??
                                "A backtest provides historical empirical evidence under simulated conditions, but does NOT constitute mathematical proof of future live profitability."}
                        </p>
                        {readiness.current_proof_of_profitability?.recommended_next_step && (
                            <div className="profitability-nextstep">
                                <strong>Recommended Action:</strong> {readiness.current_proof_of_profitability.recommended_next_step}
                            </div>
                        )}
                    </div>

                    <ul className="checks">
                        {readiness.checks.map((c) => (
                            <li key={c.name} className={c.passed ? "pass" : "fail"}>
                                <span className="mark">{c.passed ? "✓" : "✗"}</span>
                                <span className="cname">{c.name.replace(/_/g, " ")}</span>
                                <span className="cnote muted">{c.note}</span>
                            </li>
                        ))}
                    </ul>
                    <p className="disclaimer">{readiness.disclaimer}</p>
                </div>
            )}

            <h3 className="sub">Equity curve</h3>
            <EquityChart data={equity} />
            <h3 className="sub">Drawdown</h3>
            <DrawdownChart data={equity} />

            <h3 className="sub">Monthly returns</h3>
            <div className="row wrap">
                {Object.entries(monthly).map(([m, v]) => (
                    <span key={m} className={`chip ${v >= 0 ? "pos" : "neg"}`}>{m}: {v.toFixed(2)}%</span>
                ))}
                {Object.keys(monthly).length === 0 && <span className="muted">—</span>}
            </div>

            <h3 className="sub">Trades ({trades.length})</h3>
            <input placeholder="filter (LONG/SHORT/STOP_LOSS/…)" value={filter} onChange={(e) => setFilter(e.target.value)} className="filter" />
            <div className="tblwrap">
                <table className="tbl">
                    <thead><tr>
                        <th>#</th><th>Side</th><th>Entry</th><th>Exit</th><th>Qty</th><th>Gross</th><th>Costs</th><th>Net</th><th>%</th><th>Reason</th>
                    </tr></thead>
                    <tbody>
                        {shown.map((t) => (
                            <tr key={t.trade_seq} className={t.net_pnl >= 0 ? "pos" : "neg"}>
                                <td>{t.trade_seq}</td><td>{t.side}</td>
                                <td>{t.entry_price.toFixed(2)}</td><td>{t.exit_price.toFixed(2)}</td>
                                <td>{t.quantity}</td><td>{t.gross_pnl.toFixed(2)}</td>
                                <td>{(t.brokerage + t.slippage_cost + t.other_costs).toFixed(2)}</td>
                                <td>{t.net_pnl.toFixed(2)}</td><td>{t.pnl_pct.toFixed(2)}</td><td>{t.exit_reason}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {shown.length === 0 && <p className="muted">No trades.</p>}
            </div>
        </section>
    );
}
