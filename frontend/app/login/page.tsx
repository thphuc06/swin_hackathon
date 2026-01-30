export default function LoginPage() {
  return (
    <div className="min-h-screen px-6 py-10">
      <div className="mx-auto max-w-md">
        <div className="card p-8">
          <p className="section-title">Secure Login</p>
          <h1 className="mt-3 text-3xl font-semibold">Welcome back</h1>
          <p className="subtle mt-2">
            Cognito-hosted login for demo. Use testuser / MyPassword123! in local
            mode.
          </p>
          <form className="mt-6 space-y-4">
            <div>
              <label className="subtle">Email</label>
              <input className="input mt-2" placeholder="you@bank.local" />
            </div>
            <div>
              <label className="subtle">Password</label>
              <input
                className="input mt-2"
                placeholder="password"
                type="password"
              />
            </div>
            <button className="button w-full" type="button">
              Continue
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
