import { useState } from "react";
import { api } from "../api/client";

export default function DataUpload({ onUploaded }: { onUploaded: () => void }) {
    const [file, setFile] = useState<File | null>(null);
    const [symbol, setSymbol] = useState("SENSEX");
    const [exchange, setExchange] = useState("BSE");
    const [timeframe, setTimeframe] = useState("1m");
    const [requireOi, setRequireOi] = useState(false);
    const [msg, setMsg] = useState<string | null>(null);
    const [err, setErr] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    async function submit(e: React.FormEvent) {
        e.preventDefault();
        if (!file) { setErr("choose a .csv file"); return; }
        setBusy(true); setErr(null); setMsg(null);
        try {
            const r = await api.uploadCsv(file, { symbol, exchange, timeframe, require_oi: String(requireOi) });
            setMsg(`Stored ${r.candles} candles for ${r.symbol}/${r.exchange} ${r.timeframe}${r.warnings?.length ? ` (${r.warnings.length} warning)` : ""}`);
            onUploaded();
        } catch (e: any) {
            setErr(e.message);
        } finally {
            setBusy(false);
        }
    }

    return (
        <section>
            <h2>Historical Data Upload</h2>
            <p className="muted">CSV columns: timestamp (tz-aware), open, high, low, close, volume [, open_interest]. Invalid files are rejected with per-row errors.</p>
            <form onSubmit={submit} className="form">
                <div className="row">
                    <label>Symbol <input value={symbol} onChange={(e) => setSymbol(e.target.value)} required /></label>
                    <label>Exchange <input value={exchange} onChange={(e) => setExchange(e.target.value)} required /></label>
                    <label>Timeframe
                        <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                            {["1m", "5m", "15m", "30m", "1h", "1d"].map((t) => <option key={t}>{t}</option>)}
                        </select>
                    </label>
                </div>
                <div className="row">
                    <label className="chk"><input type="checkbox" checked={requireOi} onChange={(e) => setRequireOi(e.target.checked)} /> Require Open Interest</label>
                    <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                </div>
                <button type="submit" disabled={busy}>{busy ? "Uploading…" : "Upload CSV"}</button>
            </form>
            {msg && <p className="ok">{msg}</p>}
            {err && <p className="error">{err}</p>}
        </section>
    );
}
