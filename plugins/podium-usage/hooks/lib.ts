import type { Compaction, Locale, UsageRow } from '../types'

// `opencode run` at the start of a command, after a separator, space, or quote.
const RUN = /(^|[\s;&|(`'"])(opencode\s+run)(?=\s|$)([^;&|\n]*)/g
// Flags where the command already chose its own session.
const OWN = /(^|\s)(--session|-s|--continue|-c)(=|\s|$)/

export const hasOpencodeRun = (command: string) => /(^|[\s;&|(`'"])opencode\s+run(\s|$)/.test(command)

/** Prefix of every OpenCode session launched from Claude's session `sessionId`. */
export const sessionPrefix = (sessionId: string) => `ses_cc${sessionId.replace(/-/g, '')}x`

/** Appends `--session <prefix><unique>` to each `opencode run` without its own session. */
export function tagCommand(command: string, sessionId: string, now: number): string {
  let n = 0
  return command.replace(RUN, (all, lead: string, run: string, rest: string) =>
    OWN.test(rest)
      ? all
      : `${lead}${run} --session ${sessionPrefix(sessionId)}${now.toString(36)}${(n++).toString(36)}${rest}`,
  )
}

/** One row per model with compactions summed. */
export function compactionRows(list: readonly Compaction[]): UsageRow[] {
  const byModel = new Map<string, UsageRow>()
  for (const c of list) {
    const row = byModel.get(c.model) ?? {
      engine: 'compact', model: c.model, variant: '', in: 0, out: 0, cacheRead: 0, cacheWrite: 0, n: 0, quotaAt: null,
    }
    row.in += c.in
    row.out += c.out
    row.cacheRead += c.cacheRead
    row.cacheWrite += c.cacheWrite
    row.n += 1
    byModel.set(c.model, row)
  }
  return [...byModel.values()]
}

export function fmt(n: number): string {
  if (n === 0) return '0'
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}K`
  return `${(n / 1_000_000).toFixed(n < 10_000_000 ? 2 : 1)}M`
}

/** Short label: no provider prefix, no leading `claude-`, includes the OpenCode variant. */
export function label(row: UsageRow, locale: Pick<Locale, 'no_variant' | 'compaction_suffix'>): string {
  const model = row.model.replace(/^[^/]+\//, '').replace(/^claude-/, '')
  if (row.engine === 'compact') return `${model} ${locale.compaction_suffix}${row.n}`
  return row.engine === 'opencode' ? `${model} #${row.variant || locale.no_variant}` : model
}

/** New tokens that hit the model: fresh + cache-written (cache re-read does not count). */
export const inputTokens = (row: UsageRow) => row.in + row.cacheWrite

export function totals(rows: readonly UsageRow[]): { inputTokens: number; outputTokens: number } {
  return rows.reduce(
    (t, r) => ({ inputTokens: t.inputTokens + inputTokens(r), outputTokens: t.outputTokens + r.out }),
    { inputTokens: 0, outputTokens: 0 },
  )
}

// Relevance order from the orchestrator's table; anything missing falls to the end.
// Built at call time from the configured `model_order` (regex fragments).
const VARIANT_ORDER = ['xhigh', 'high', 'medium', 'thinking', 'low', 'none', '']

const rank = (list: readonly unknown[], i: number) => (i === -1 ? list.length : i)

/** Compile the configured fragments into case-insensitive regexes, falling back to the default. */
export function buildModelOrder(fragments: readonly string[]): readonly RegExp[] {
  const out: RegExp[] = []
  for (const f of fragments) {
    try {
      out.push(new RegExp(f, 'i'))
    } catch {
      // Skip invalid fragments instead of breaking the whole ordering.
    }
  }
  return out.length > 0 ? out : DEFAULT_MODEL_ORDER
}

// Reasonable fallback if runtime.json is missing or unusable.
const DEFAULT_MODEL_ORDER: readonly RegExp[] = [
  /opus/i, /sonnet/i, /haiku/i, /gpt-6\.1-sol/i, /gpt-6-luna/i, /gpt/i, /minimax/i,
]

/** By model relevance, then variant relevance; compactions go last. */
export function byRelevance(rows: readonly UsageRow[], fragments: readonly string[]): UsageRow[] {
  const order = buildModelOrder(fragments)
  const model = (r: UsageRow) => rank(order, order.findIndex(re => re.test(r.model)))
  const variant = (r: UsageRow) => rank(VARIANT_ORDER, VARIANT_ORDER.indexOf(r.variant))
  return [...rows].sort(
    (a, b) =>
      Number(a.engine === 'compact') - Number(b.engine === 'compact') ||
      model(a) - model(b) ||
      a.model.localeCompare(b.model) ||
      variant(a) - variant(b),
  )
}

const hhmm = (d: Date) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`

/** `today 19:50` or `Thu 22 11:00` (localised weekday names). */
export function shortDate(
  at: number | string,
  now: number,
  locale: Pick<Locale, 'short_today' | 'weekdays'>,
): string {
  const d = new Date(at)
  const nowDate = new Date(now)
  if (d.toDateString() === nowDate.toDateString()) return `${locale.short_today}${hhmm(d)}`
  const wd = locale.weekdays[d.getDay()] ?? ''
  return `${wd} ${d.getDate()} ${hhmm(d)}`
}