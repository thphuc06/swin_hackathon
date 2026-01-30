export const mockBalances = {
  available: 58230000,
  jars: [
    { id: "jar-emergency", name: "Emergency Buffer", balance: 12000000, target: 20000000 },
    { id: "jar-house", name: "House Goal", balance: 18000000, target: 650000000 },
    { id: "jar-life", name: "Life", balance: 9000000, target: 15000000 },
  ],
};

export const incomeSources = [
  { source: "Salary", monthly: 28000000, change: "+3.2%" },
  { source: "Freelance", monthly: 6200000, change: "-4.1%" },
  { source: "Rental", monthly: 4500000, change: "stable" },
];

export const notifications = [
  {
    id: "n1",
    title: "Dining spend spiked 42% vs 30d average",
    detail: "We detected VND 4.2M dining spend in 7 days. Consider moving to Essentials jar.",
    time: "2h ago",
  },
  {
    id: "n2",
    title: "House jar below weekly plan",
    detail: "Target weekly contribution is VND 1.8M. Current trend is -0.6M.",
    time: "Yesterday",
  },
];

export const chatSamples = [
  {
    role: "user",
    text: "When can I buy a house if I keep saving 8M per month?",
  },
  {
    role: "assistant",
    text: "Based on the last 60 days, your average net savings is 7.6M. With a 650M target, your ETA range is 6.8–7.4 years assuming inflation at 4% and income growth at 3%. See policy KB-03, KB-07. Trace: trc_01H...",
  },
];

export const transactions = [
  { id: "t1", date: "2026-01-28", merchant: "VinMart", amount: 820000, jar: "Life" },
  { id: "t2", date: "2026-01-26", merchant: "Techcombank", amount: 5500000, jar: "House" },
  { id: "t3", date: "2026-01-24", merchant: "Gojek", amount: 210000, jar: "Life" },
];
