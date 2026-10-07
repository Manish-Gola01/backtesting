import { useEffect, useState } from "react";
import { api, type InstrumentCoverage } from "../api/client";

export default function Dashboard() {
    const [cov, setCov] = useState<InstrumentCoverage[]>([]);
    const [err, setErr] = useState<string | null>(null);

    useEffect(() => {
        api.instruments().then((r) => setCov(r.instruments)).catch((e) => setErr(e.message));
    }, []);

    return (
        <section>
            <h2>Dashboard</h2>
            <p className="muted">Uploaded market data coverage. Upload CSVs on the Data page.</p>
            {err && <p className="error">{err}</p>}
            {cov.length === 0 && !err && <p className="muted">No data uploaded yet.</p>}
            {cov.length > 0 && (
                <table className="tbl">
                    <thead>
                        <tr><th>Symbol</th><th>Exchange</th><th>TF</th><th>OI</th><th>Candles</th><th>Range</th></tr>
                    </thead>
                    <tbody>
                        {cov.map((c) => (
                            <tr key={`${c.symbol}/${c.exchange}/${c.timeframe}`}>
                                <td>{c.symbol}</td><td>{c.exchange}</td><td>{c.timeframe}</td>
                                <td>{c.has_oi ? "✓" : "—"}</td><td>{c.candles}</td>
                                <td className="muted">{c.start.slice(0, 10)} → {c.end.slice(0, 10)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </section>
    );
}
