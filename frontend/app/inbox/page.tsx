import AppShell from "@/components/AppShell";
import { notifications } from "@/lib/mock";

export default function InboxPage() {
  return (
    <AppShell
      title="Tier1 Notifications"
      subtitle="Event-driven insights for spend anomalies and balance risks."
    >
      <section className="card p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="section-title">Alerts</p>
            <h2 className="mt-2 text-xl font-semibold">Recent insights</h2>
          </div>
          <button className="button-secondary">Mark all read</button>
        </div>
        <div className="mt-6 space-y-4">
          {notifications.map((note) => (
            <div key={note.id} className="rounded-2xl border border-slate/10 bg-white/80 p-4">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-semibold">{note.title}</p>
                  <p className="subtle mt-1">{note.detail}</p>
                </div>
                <span className="badge">{note.time}</span>
              </div>
              <div className="mt-3 text-xs text-slate/60">
                Source: Tier1 rules engine • Trace: trc_01HFT...
              </div>
            </div>
          ))}
        </div>
      </section>
    </AppShell>
  );
}
