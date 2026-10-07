import { useState } from "react";
import Dashboard from "./pages/Dashboard";
import DataUpload from "./pages/DataUpload";
import Backtest from "./pages/Backtest";
import Results from "./pages/Results";

type Page = "dashboard" | "data" | "backtest" | "results";

const NAV: { id: Page; label: string }[] = [
    { id: "dashboard", label: "Dashboard" },
    { id: "data", label: "Data" },
    { id: "backtest", label: "Backtest" },
    { id: "results", label: "Results" },
];

export default function App() {
    const [page, setPage] = useState<Page>("dashboard");
    const [resultId, setResultId] = useState<string | null>(null);
    const [, setTick] = useState(0); // refresh dashboard after upload

    return (
        <div className="app">
            <header className="topbar">
                <div className="brand">Algo Backtesting</div>
                <nav>
                    {NAV.map((n) => (
                        <button key={n.id} className={page === n.id ? "nav active" : "nav"} onClick={() => setPage(n.id)}>
                            {n.label}
                        </button>
                    ))}
                </nav>
            </header>
            <main className="content">
                {page === "dashboard" && <Dashboard />}
                {page === "data" && <DataUpload onUploaded={() => setTick((t) => t + 1)} />}
                {page === "backtest" && <Backtest onDone={(id) => { setResultId(id); setPage("results"); }} />}
                {page === "results" && <Results id={resultId} />}
            </main>
        </div>
    );
}
