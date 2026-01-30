import AppShell from "@/components/AppShell";
import { mockBalances } from "@/lib/mock";

export default function TransferPage() {
  return (
    <AppShell
      title="Transfer Funds"
      subtitle="Jar-first transfer flow for transparency and budgeting."
    >
      <section className="card p-6">
        <form className="grid gap-6 lg:grid-cols-2">
          <div className="space-y-4">
            <div>
              <label className="subtle">From Jar</label>
              <select className="input mt-2">
                {mockBalances.jars.map((jar) => (
                  <option key={jar.id} value={jar.id}>
                    {jar.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="subtle">Subcategory</label>
              <select className="input mt-2">
                <option>Essentials / Rent</option>
                <option>Essentials / Utilities</option>
                <option>Life / Dining</option>
                <option>Life / Transport</option>
                <option>House / Savings</option>
              </select>
            </div>
            <div>
              <label className="subtle">Amount</label>
              <input className="input mt-2" placeholder="VND 0" />
            </div>
            <div>
              <label className="subtle">Counterparty</label>
              <input className="input mt-2" placeholder="Merchant or recipient" />
            </div>
          </div>
          <div className="space-y-4">
            <div className="rounded-2xl border border-slate/10 bg-sand/70 p-4">
              <p className="section-title">Compliance</p>
              <p className="subtle mt-2">
                Transfers must be tagged with jar + subcategory to keep budget
                integrity and Tier1 alerts accurate.
              </p>
            </div>
            <div className="rounded-2xl border border-slate/10 bg-white/70 p-4">
              <p className="section-title">Confirmation</p>
              <p className="subtle mt-2">
                This is a simulator. No real money will move.
              </p>
              <button className="button mt-4 w-full" type="button">
                Confirm Transfer
              </button>
            </div>
          </div>
        </form>
      </section>
    </AppShell>
  );
}
