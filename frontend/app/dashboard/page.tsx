import AppShell from "@/components/AppShell";
import { incomeSources, mockBalances, transactions } from "@/lib/mock";

function formatCurrency(value: number) {
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
    maximumFractionDigits: 0,
  }).format(value);
}

export default function DashboardPage() {
  return (
    <AppShell
      title="Retail Overview"
      subtitle="Real-time snapshot for balance, jars, and income sources."
    >
      <section className="grid gap-4 lg:grid-cols-3">
        <div className="card p-6">
          <p className="section-title">Available Balance</p>
          <p className="mt-4 text-3xl font-semibold font-mono">
            {formatCurrency(mockBalances.available)}
          </p>
          <p className="subtle mt-2">Updated from rolling 60d ledger.</p>
        </div>
        <div className="card p-6">
          <p className="section-title">Risk Profile</p>
          <p className="mt-4 text-2xl font-semibold">Balanced</p>
          <p className="subtle mt-2">Last updated Jan 18, 2026.</p>
        </div>
        <div className="card p-6">
          <p className="section-title">Goal</p>
          <p className="mt-4 text-2xl font-semibold">House Purchase</p>
          <p className="subtle mt-2">Target 650M • ETA 6.8–7.4 years</p>
        </div>
      </section>

      <section className="card p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="section-title">Jars Overview</p>
            <h2 className="mt-2 text-xl font-semibold">Jar allocations</h2>
          </div>
          <button className="button-secondary">Manage Jars</button>
        </div>
        <div className="mt-6 grid gap-4 lg:grid-cols-3">
          {mockBalances.jars.map((jar) => (
            <div key={jar.id} className="rounded-2xl border border-slate/10 bg-sand/70 p-4">
              <p className="text-sm uppercase tracking-[0.2em] text-slate/60">
                {jar.name}
              </p>
              <p className="mt-3 text-lg font-semibold">
                {formatCurrency(jar.balance)}
              </p>
              <p className="subtle mt-1">
                Target {formatCurrency(jar.target)}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div className="card p-6">
          <p className="section-title">Income Sources Summary</p>
          <h2 className="mt-2 text-xl font-semibold">Multi-source cash flow</h2>
          <table className="table mt-4">
            <thead>
              <tr>
                <th>Source</th>
                <th>Monthly</th>
                <th>Trend</th>
              </tr>
            </thead>
            <tbody>
              {incomeSources.map((source) => (
                <tr key={source.source}>
                  <td>{source.source}</td>
                  <td className="font-mono">{formatCurrency(source.monthly)}</td>
                  <td className="text-slate">{source.change}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="button-secondary mt-4">Update Sources</button>
        </div>

        <div className="card p-6">
          <p className="section-title">Recent Activity</p>
          <h2 className="mt-2 text-xl font-semibold">Largest transactions</h2>
          <ul className="mt-4 space-y-3">
            {transactions.map((txn) => (
              <li key={txn.id} className="rounded-2xl border border-slate/10 bg-white/70 p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold">{txn.merchant}</p>
                    <p className="subtle">{txn.date} • {txn.jar}</p>
                  </div>
                  <span className="font-mono">-{formatCurrency(txn.amount)}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </AppShell>
  );
}
