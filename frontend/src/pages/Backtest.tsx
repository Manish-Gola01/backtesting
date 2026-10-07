import { useEffect, useState } from "react";
import { api, type InstrumentCoverage, type StrategyInfo } from "../api/client";

// Dynamic strategy parameter field, driven by the strategy's param_schema.
function ParamField({ name, spec, value, onChange }: {
    name: string; spec: any; value: any; onChange: (v: any) => void;
}) {
    const label = <span className="pname" title={spec.description}>{name}</span>;
    if (spec.type === "bool") {
        return <label className="field">{label}<input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /></label>;
    }
    if (spec.options) {
        return <label className="field">{label}
            <select value={value} onChange={(e) => onChange(e.target.value)}>
                {spec.options.map((o: string) => <option key={o}>{o}</option>)}
            </select></label>;
    }
    return <label className="field">{label}
        <input type="number" step="any" value={value} min={spec.min} max={spec.max}
            onChange={(e) => onChange(spec.type === "int" ? parseInt(e.target.value) : parseFloat(e.target.value))} />
    </label>;
}

export default function Backtest({ onDone }: { onDone: (id: string) => void }) {
    const [instruments, setInstruments] = useState<InstrumentCoverage[]>([]);
    const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
    const [strategy, setStrategy] = useState<StrategyInfo | null>(null);
    const [params, setParams] = useState<Record<string, any>>({});
    const [symbol, setSymbol] = useState(""); const [exchange, setExchange] = useState(""); const [timeframe, setTimeframe] = useState("1m");
    const [capital, setCapital] = useState(100000);
    const [sizingModel, setSizingModel] = useState("risk_pct"); const [sizingValue, setSizingValue] = useState(1);
    const [sl, setSl] = useState(1); const [tp, setTp] = useState(2);
    const [brokerage, setBrokerage] = useState(0); const [slippage, setSlippage] = useState(0);
    const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
    const [status, setStatus] = useState<string | null>(null);

    useEffect(() => {
        api.instruments().then((r) => {
            setInstruments(r.instruments);
            if (r.instruments[0]) { setSymbol(r.instruments[0].symbol); setExchange(r.instruments[0].exchange); setTimeframe(r.instruments[0].timeframe); }
        }).catch((e) => setErr(e.message));
        api.strategies().then(async (list) => {
            setStrategies(list);
            if (list[0]) {
                const full = await api.strategy(list[0].name);
                setStrategy(full);
                setParams(Object.fromEntries(Object.entries(full.param_schema).map(([k, v]) => [k, v.default])));
            }
        }).catch((e) => setErr(e.message));
    }, []);

    function pickInstrument(key: string) {
        const [s, e, t] = key.split("/");
        setSymbol(s); setExchange(e); setTimeframe(t);
    }
    async function pickStrategy(name: string) {
        const full = await api.strategy(name);
        setStrategy(full);
        setParams(Object.fromEntries(Object.entries(full.param_schema).map(([k, v]) => [k, v.default])));
    }

    async function run(e: React.FormEvent) {
        e.preventDefault();
        setBusy(true); setErr(null); setStatus(null);
        try {
            const created = await api.createBacktest({
                strategy: strategy?.name, symbol, exchange, timeframe, initial_capital: capital,
                params, sizing: { model: sizingModel, value: sizingValue },
                costs: { brokerage_per_trade: brokerage, slippage_pct: slippage },
                stop_loss_pct: sl, take_profit_pct: tp, warmup: params.lookback ?? 0,
            });
            // poll until terminal
            const id = created.id;
            for (; ;) {
                const st = await api.backtestStatus(id);
                setStatus(st.status);
                if (st.status === "COMPLETED") { onDone(id); return; }
                if (st.status === "FAILED") { setErr(st.error ?? "backtest failed"); return; }
                await new Promise((r) => setTimeout(r, 500));
            }
        } catch (e: any) {
            setErr(e.message);
        } finally {
            setBusy(false);
        }
    }

    return (
        <section>
            <h2>Run Backtest</h2>
            {instruments.length === 0 && <p className="muted">No data yet — upload a CSV on the Data page first.</p>}
            <form onSubmit={run} className="form">
                <div className="row">
                    <label className="field">Instrument
                        <select value={`${symbol}/${exchange}/${timeframe}`} onChange={(e) => pickInstrument(e.target.value)}>
                            {instruments.map((i) => <option key={`${i.symbol}/${i.exchange}/${i.timeframe}`}>{`${i.symbol}/${i.exchange}/${i.timeframe}`}</option>)}
                        </select></label>
                    <label className="field">Strategy
                        <select value={strategy?.name} onChange={(e) => pickStrategy(e.target.value)}>
                            {strategies.map((s) => <option key={s.name}>{s.name}</option>)}
                        </select></label>
                    <label className="field">Initial Capital
                        <input type="number" value={capital} onChange={(e) => setCapital(parseFloat(e.target.value))} /></label>
                </div>

                {strategy && (
                    <>
                        <h3 className="sub">Strategy parameters</h3>
                        <div className="row wrap">
                            {Object.entries(strategy.param_schema).map(([name, spec]) => (
                                <ParamField key={name} name={name} spec={spec} value={params[name]} onChange={(v) => setParams((p) => ({ ...p, [name]: v }))} />
                            ))}
                        </div>
                    </>
                )}

                <h3 className="sub">Risk &amp; costs</h3>
                <div className="row wrap">
                    <label className="field">Sizing
                        <select value={sizingModel} onChange={(e) => setSizingModel(e.target.value)}>
                            <option value="fixed_qty">fixed qty</option><option value="fixed_amount">fixed amount</option>
                            <option value="pct_capital">% capital</option><option value="risk_pct">risk %</option>
                        </select></label>
                    <label className="field">Size value<input type="number" step="any" value={sizingValue} onChange={(e) => setSizingValue(parseFloat(e.target.value))} /></label>
                    <label className="field">Stop loss %<input type="number" step="any" value={sl} onChange={(e) => setSl(parseFloat(e.target.value))} /></label>
                    <label className="field">Take profit %<input type="number" step="any" value={tp} onChange={(e) => setTp(parseFloat(e.target.value))} /></label>
                    <label className="field">Brokerage/trade<input type="number" step="any" value={brokerage} onChange={(e) => setBrokerage(parseFloat(e.target.value))} /></label>
                    <label className="field">Slippage %<input type="number" step="any" value={slippage} onChange={(e) => setSlippage(parseFloat(e.target.value))} /></label>
                </div>

                <button type="submit" disabled={busy || !strategy}>{busy ? `Running… ${status ?? ""}` : "Run Backtest"}</button>
            </form>
            {err && <p className="error">{err}</p>}
        </section>
    );
}
