// ---- Types mirroring the backend API (no fake data anywhere) ----
export interface HealthResponse {
    status: string; app: string; version: string; environment: string; timestamp: string;
}
export interface InstrumentCoverage {
    symbol: string; exchange: string; timeframe: string; has_oi: boolean;
    candles: number; start: string; end: string;
}
export interface StrategyInfo {
    name: string; description: string; param_schema: Record<string, ParamSpec>;
}
export interface ParamSpec {
    type: string; default: any; min?: number; max?: number; options?: string[]; description?: string;
}
export interface BacktestCreated { id: string; status: string; }
export interface BacktestStatus {
    id: string; status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
    error?: string; created_at: string; started_at?: string; finished_at?: string;
}
export interface Trade {
    trade_seq: number; symbol: string; strategy: string; side: "LONG" | "SHORT";
    entry_time: string; entry_price: number; exit_time: string; exit_price: number;
    quantity: number; stop_loss?: number; take_profit?: number;
    gross_pnl: number; brokerage: number; slippage_cost: number; other_costs: number;
    net_pnl: number; pnl_pct: number; exit_reason: string; holding_seconds: number;
}
export interface Metrics { [k: string]: any; }
export interface EquityPoint { timestamp: string; equity: number; drawdown: number; }
export interface ReadinessCheck { name: string; passed: boolean; value: any; note: string; }
export interface ProofOfProfitabilityInfo {
    has_empirical_edge: boolean;
    status: string;
    is_guaranteed_proof: boolean;
    summary: string;
    live_validation_required: boolean;
    recommended_next_step: string;
}
export interface LiveTradingReadinessInfo {
    verdict: string;
    verdict_note: string;
    readiness_score: number;
    checks_passed: number;
    checks_total: number;
    critical_checks_passed: boolean;
}
export interface ReadinessReport {
    verdict: string;
    verdict_note: string;
    readiness_score: number;
    checks_passed: number;
    checks_total: number;
    checks: ReadinessCheck[];
    disclaimer: string;
    is_proof_of_profitability: boolean;
    live_trading_readiness?: LiveTradingReadinessInfo;
    current_proof_of_profitability?: ProofOfProfitabilityInfo;
}

const API_BASE = "/api/v1";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`, init);
    if (!res.ok) {
        let detail: any = `HTTP ${res.status}`;
        try { const j = await res.json(); detail = j.detail?.detail ?? j.detail ?? detail; } catch { }
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.json() as Promise<T>;
}

export const api = {
    health: () => req<HealthResponse>("/health"),
    instruments: () => req<{ instruments: InstrumentCoverage[] }>("/instruments"),
    strategies: () => req<StrategyInfo[]>("/strategies"),
    strategy: (name: string) => req<StrategyInfo>(`/strategies/${name}`),
    createBacktest: (payload: any) =>
        req<BacktestCreated>("/backtests", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
    backtestStatus: (id: string) => req<BacktestStatus>(`/backtests/${id}`),
    trades: (id: string) => req<Trade[]>(`/backtests/${id}/trades`),
    metrics: (id: string) => req<{ metrics: Metrics }>(`/backtests/${id}/metrics`),
    equity: (id: string) => req<EquityPoint[]>(`/backtests/${id}/equity`),
    monthly: (id: string) => req<{ monthly_returns: Record<string, number> }>(`/backtests/${id}/monthly-performance`),
    readiness: (id: string) => req<ReadinessReport>(`/backtests/${id}/readiness`),
    uploadCsv: async (file: File, q: Record<string, string>) => {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch(`${API_BASE}/data/upload?${new URLSearchParams(q)}`, { method: "POST", body: fd });
        const j = await res.json();
        if (!res.ok) throw new Error(j.detail?.detail ?? JSON.stringify(j.detail));
        return j;
    },
};

