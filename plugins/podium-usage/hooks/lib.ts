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

/** Short label: no provider prefix, no leading `claude-`, includes the OpenCode
 * variant and, for Claude rows, the effort bucket from the transcript. */
export function label(row: UsageRow, locale: Pick<Locale, 'no_variant' | 'compaction_suffix'>): string {
  const model = row.model.replace(/^[^/]+\//, '').replace(/^claude-/, '')
  if (row.engine === 'compact') return `${model} ${locale.compaction_suffix}${row.n}`
  if (row.engine === 'opencode') return `${model} #${row.variant || locale.no_variant}`
  return row.variant ? `${model} #${row.variant}` : model
}

/** New tokens that hit the model: fresh + cache-written (cache re-read does not count). */
export const inputTokens = (row: UsageRow) => row.in + row.cacheWrite

export function totals(rows: readonly UsageRow[]): { inputTokens: number; outputTokens: number } {
  return rows.reduce(
    (t, r) => ({ inputTokens: t.inputTokens + inputTokens(r), outputTokens: t.outputTokens + r.out }),
    { inputTokens: 0, outputTokens: 0 },
  )
}

// Variant order: anything not in this list falls to the end. Used after the
// configured `model_order` regexes have matched (or not matched) a row.
const VARIANT_ORDER = ['xhigh', 'high', 'medium', 'thinking', 'low', 'none', '']

const rank = (list: readonly unknown[], i: number) => (i === -1 ? list.length : i)

/** Compile the configured fragments into case-insensitive regexes. Returns
 * `null` when no usable fragment is provided so the caller can fall back to
 * the neutral "order by total tokens descending" behaviour. */
export function buildModelOrder(fragments: readonly string[]): readonly RegExp[] | null {
  const out: RegExp[] = []
  for (const f of fragments) {
    try {
      out.push(new RegExp(f, 'i'))
    } catch {
      // Skip invalid fragments instead of breaking the whole ordering.
    }
  }
  return out.length > 0 ? out : null
}

// `inputTokens` is a function on this file already; reuse it for the neutral
// fallback so callers sort by "tokens that actually hit the model".
const totalTokens = (r: UsageRow): number => inputTokens(r) + r.out

/** By model relevance, then variant relevance; compactions go last. When no
 * configured fragments are usable (runtime.json missing or `usage.model_order`
 * empty/unparseable), rows are ordered by total tokens descending — a neutral
 * fallback that carries no personal roster names. */
export function byRelevance(rows: readonly UsageRow[], fragments: readonly string[]): UsageRow[] {
  const order = buildModelOrder(fragments)
  if (order === null) {
    const compacts: UsageRow[] = []
    const rest: UsageRow[] = []
    for (const r of rows) (r.engine === 'compact' ? compacts : rest).push(r)
    rest.sort((a, b) =>
      totalTokens(b) - totalTokens(a) ||
      a.model.localeCompare(b.model) ||
      a.variant.localeCompare(b.variant),
    )
    return [...rest, ...compacts]
  }
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