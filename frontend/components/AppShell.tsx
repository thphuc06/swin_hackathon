import Link from "next/link";

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/transfer", label: "Transfer" },
  { href: "/inbox", label: "Inbox" },
  { href: "/chat", label: "Chat" },
];

export default function AppShell({
  children,
  title,
  subtitle,
}: {
  children: React.ReactNode;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="min-h-screen px-6 py-8 lg:px-10">
      <div className="mx-auto flex max-w-6xl flex-col gap-8">
        <header className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="section-title">Jars Fintech Simulator</p>
            <h1 className="mt-2 text-3xl font-semibold text-ink lg:text-4xl">
              {title}
            </h1>
            {subtitle ? <p className="subtle mt-2">{subtitle}</p> : null}
          </div>
          <div className="flex items-center gap-3">
            <span className="badge">Cognito • JWT</span>
            <span className="badge">AgentCore</span>
          </div>
        </header>
        <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
          <nav className="card h-fit p-4">
            <div className="space-y-2 text-sm">
              {navItems.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="block rounded-xl px-3 py-2 text-slate hover:bg-sand/70 hover:text-ink"
                >
                  {item.label}
                </Link>
              ))}
            </div>
          </nav>
          <main className="flex flex-col gap-6">{children}</main>
        </div>
      </div>
    </div>
  );
}
