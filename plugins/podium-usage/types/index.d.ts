export type UsageRow = {
  engine: 'claude' | 'opencode' | 'compact'
  model: string
  variant: string
  in: number
  out: number
  cacheRead: number
  cacheWrite: number
  n: number
  quotaAt: number | null
}

export type Compaction = {
  model: string
  at: number
  in: number
  out: number
  cacheRead: number
  cacheWrite: number
}

export type Limit = { kind: string; percentUsed: number; resetsAt: string | null }

export type Report = {
  sessionId: string
  rows: UsageRow[]
  errors: string[]
  usd: number | null
  limits: Limit[]
  at: number
}

// Locale bundle consumed by the mod. Mirrors locales/<ui>.json.
export type Locale = {
  pane_title: string
  command_description: string
  command_opened: string
  computing: string
  header_session: string
  header_input: string
  header_output: string
  group_claude: string
  group_opencode: string
  empty_rows: string
  cost_session: string
  engine_claude: string
  engine_opencode: string
  limit_5h: string
  limit_7d: string
  limit_resets: string
  limit_resets_close: string
  quota_exhausted: string
  no_variant: string
  compaction_suffix: string
  short_today: string
  weekdays: readonly string[]
}

// Runtime config consumed by the mod. Mirrors runtime.json §9.2.
export type UsageRuntime = {
  ui: 'en' | 'es'
  usage: { model_order: readonly string[] }
}

declare module 'claude-code' {
  interface PluginState {
    'podium-usage': { report: Report | null; runtime: UsageRuntime | null; locale: Locale }
  }
}