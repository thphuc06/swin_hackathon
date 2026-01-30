import Link from "next/link";

export default function Home() {
  return (
    <div className="min-h-screen px-6 py-10">
      <div className="mx-auto flex max-w-3xl flex-col gap-10">
        <header className="card p-8">
          <p className="section-title">Jars Fintech MVP</p>
          <h1 className="mt-4 text-4xl font-semibold text-ink">
            Banking Simulator + AgentCore Advisory
          </h1>
          <p className="subtle mt-4">
            Clean, minimal demo for Tier1 insights + Tier2 advisory with audit-ready
            explainability.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/login" className="button">
              Continue to Login
            </Link>
            <Link href="/dashboard" className="button-secondary">
              View Demo Dashboard
            </Link>
          </div>
        </header>
        <section className="card p-8">
          <h2 className="text-xl font-semibold">What you can demo</h2>
          <ul className="mt-4 space-y-2 text-sm text-slate">
            <li>Tier1 alerts in Inbox (budget drift, low balance).</li>
            <li>Tier2 advisory chat with citations + trace id.</li>
            <li>Jar-first transfer flow with subcategory requirement.</li>
            <li>Income sources summary to handle multi-source cashflow.</li>
          </ul>
        </section>
      </div>
    </div>
  );
}
