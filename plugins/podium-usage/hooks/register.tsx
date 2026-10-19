import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Compaction, Locale, Report, UsageRow, UsageRuntime } from '../types'
import { byRelevance, compactionRows, fmt, hasOpencodeRun, inputTokens, label, shortDate, tagCommand, totals } from './lib'

const PANE = 'podium-usage'
const REFRESH_MS = 30_000

const report = atom({ plugin: 'podium-usage', key: 'report' } as const, null)
const runtime = atom({ plugin: 'podium-usage', key: 'runtime' } as const, null)
const locale = atom({ plugin: 'podium-usage', key: 'locale' } as const, null)

const compactKey = (sessionId: string) => `compact:${sessionId}`

let isRefreshing = false

// Recomputes everything: transcripts + opencode.db + stored compactions + runtime + locale.
async function refresh($: EngineInterface) {
  if (isRefreshing) return
  isRefreshing = true
  try {
    const sessionId = await $.session.id()
    const ran = await $.process.run(
      ['python3', '-I', `${$.plugin.root}/scripts/session_usage.py`, sessionId],
      { timeoutMs: 60_000 },
    )
    const errors: string[] = []
    let rows: UsageRow[] = []
    let parsedRuntime: UsageRuntime | null = null
    let parsedLocale: Locale | null = null
    try {
      const data = JSON.parse(ran.stdout) as {
        rows: UsageRow[]
        errors: string[]
        runtime?: UsageRuntime
        locale?: Locale
      }
      rows = data.rows
      errors.push(...data.errors)
      parsedRuntime = data.runtime ?? null
      parsedLocale = data.locale ?? null
    } catch {
      const loc = (await read($, locale)) as Locale | null
      const prefix = loc?.reader_error ?? 'reader: '
      errors.push(`${prefix}${ran.stderr.trim().slice(0, 200) || `exit ${ran.exitCode}`}`)
    }
    const compactions = ((await $.store.get(compactKey(sessionId))) ?? []) as Compaction[]
    const usage = await $.session.usage()
    const next: Report = {
      sessionId,
      rows: [...rows, ...compactionRows(compactions)],
      errors,
      usd: usage.cost?.usd ?? null,
      limits: usage.rateLimits.map(l => ({ kind: l.kind, percentUsed: l.percentUsed, resetsAt: l.resetsAt ?? null })),
      at: await $.clock.now(),
    }
    await update($, report, () => next)
    if (parsedRuntime) await update($, runtime, () => parsedRuntime)
    if (parsedLocale) await update($, locale, () => parsedLocale)

    const loc = (parsedLocale ?? (await read($, locale))) as Locale | null
    const cfg = (parsedRuntime ?? (await read($, runtime))) as UsageRuntime | null
    const headerInput = loc?.header_input ?? 'input'
    const headerOutput = loc?.header_output ?? 'output'
    const engineClaude = loc?.engine_claude ?? 'Claude '
    const engineOpencode = loc?.engine_opencode ?? 'OpenCode '
    const claude = totals(next.rows.filter(r => r.engine !== 'opencode'))
    const opencode = totals(next.rows.filter(r => r.engine === 'opencode'))
    const fiveHour = next.limits.find(l => l.kind === 'five_hour')
    $.ui.status(
      [
        `${engineClaude}${fmt(claude.inputTokens)}↓ ${fmt(claude.outputTokens)}↑`,
        opencode.inputTokens + opencode.outputTokens > 0 ? `${engineOpencode}${fmt(opencode.inputTokens)}↓ ${fmt(opencode.outputTokens)}↑` : null,
        next.usd !== null ? `$${next.usd.toFixed(2)}` : null,
        fiveHour ? `5h ${fiveHour.percentUsed}%` : null,
      ]
        .filter(Boolean)
        .join(' · '),
    )
    // cfg is consumed here only to suppress the "unused" complaint; byRelevance reads
    // the same value at render time from the store.
    void cfg
  } catch {
    // A failed refresh must not break anything; the next tick retries.
  } finally {
    isRefreshing = false
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // Load the locale (and runtime) BEFORE registering the command so its
    // description follows the configured UI language. refresh() stores the
    // locale into the atom; we await it once here so `read` returns it below.
    await refresh($)
    const loc = (await read($, locale)) as Locale | null
    await $.command.register({
      name: 'tokens',
      description: loc?.command_description ?? 'Show the tokens consumed in this session, per model.',
    })
    $.clock.every(REFRESH_MS, () => void refresh($))

    return next(e)
  })

  on('command.run', { command: 'tokens' }, async $ => {
    await refresh($)
    const loc = (await read($, locale)) as Locale | null
    await $.ui.open({ id: PANE, title: loc?.pane_title ?? 'Tokens' })

    return { text: loc?.command_opened ?? 'Token pane opened.' }
  })

  // Tag every `opencode run` with the Claude session that launched it (main and subagents).
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    if (!hasOpencodeRun(e.command)) return next(e)
    const sessionId = await $.session.id()
    const ran = await next({ ...e, command: tagCommand(e.command, sessionId, await $.clock.now()) })
    void refresh($)

    return ran
  }).catch(($, e, next) => next(e)) // if the mod fails, the command still runs

  // The compaction call doesn't end up in the transcript: we store its usage here.
  on('session.compact', async ($, e, next) => {
    const done = await next(e)
    if ('usage' in done && done.usage) {
      const sessionId = await $.session.id()
      const key = compactKey(sessionId)
      const list = ((await $.store.get(key)) ?? []) as Compaction[]
      const u = done.usage
      list.push({
        model: await $.session.model(),
        at: await $.clock.now(),
        in: u.input_tokens,
        out: u.output_tokens,
        cacheRead: u.cache_read_input_tokens ?? 0,
        cacheWrite: u.cache_creation_input_tokens ?? 0,
      })
      await $.store.set(key, list)
      void refresh($)
    }

    return done
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const r = await read($, report)
    const loc = ((await read($, locale)) as Locale | null) ?? null
    const cfg = ((await read($, runtime)) as UsageRuntime | null) ?? null
    if (r === null) return <Text dimColor>{loc?.computing ?? 'Computing…'}</Text>

    const width = Math.max(10, Math.min(28, (e.viewport?.columns ?? 60) - 17))
    const line = (row: UsageRow) => (
      <Box key={`${row.engine}:${row.model}:${row.variant}`} flexDirection="column">
        <Text>
          {label(row, loc ?? fallbackLocale()).slice(0, width).padEnd(width)} {fmt(inputTokens(row)).padStart(7)} {fmt(row.out).padStart(7)}
        </Text>
        {row.quotaAt !== null && <Text color="yellow">  {(loc?.quota_exhausted ?? '⚠ quota exhausted ')}{shortDate(row.quotaAt, r.at, loc ?? fallbackLocale())}</Text>}
      </Box>
    )
    const limit = (kind: string) => r.limits.find(l => l.kind === kind)
    const limitText = (name: string, kind: string) => {
      const l = limit(kind)
      if (!l) return null
      const opens = loc?.limit_resets ?? ' (resets '
      const closes = loc?.limit_resets_close ?? ')'
      return l.resetsAt ? `${name} ${l.percentUsed}%${opens}${shortDate(l.resetsAt, r.at, loc ?? fallbackLocale())}${closes}` : `${name} ${l.percentUsed}%`
    }
    const limits = [limitText(loc?.limit_5h ?? '5h', 'five_hour'), limitText(loc?.limit_7d ?? '7d', 'seven_day')].filter(Boolean).join(' · ')
    const group = (title: string, rows: UsageRow[]) =>
      rows.length > 0 && (
        <Box key={title} flexDirection="column" marginBottom={1}>
          <Text bold>{title}</Text>
          {byRelevance(rows, cfg?.usage.model_order ?? []).map(line)}
        </Box>
      )

    return (
      <Box flexDirection="column">
        <Text dimColor>
          {(loc?.header_session ?? 'Tokens · this session').padEnd(width)} {(loc?.header_input ?? 'input').padStart(7)} {(loc?.header_output ?? 'output').padStart(7)}
        </Text>
        {group(loc?.group_claude ?? 'Claude Code', r.rows.filter(x => x.engine !== 'opencode'))}
        {group(loc?.group_opencode ?? 'OpenCode (from this session)', r.rows.filter(x => x.engine === 'opencode'))}
        {r.rows.length === 0 && <Text dimColor>{loc?.empty_rows ?? 'No usage yet.'}</Text>}
        {r.usd !== null && <Text>{(loc?.cost_session ?? 'Session cost: $')}{r.usd.toFixed(2)}</Text>}
        {limits !== '' && <Text dimColor>{loc?.engine_claude ?? 'Claude '}{limits}</Text>}
        {r.errors.map(err => (
          <Text key={err} color="red">{err}</Text>
        ))}
      </Box>
    )
  })
}

// Built-in fallback locale used before runtime.json and locales/<ui>.json are read.
// Keeps the mod functional on a freshly-installed plugin.
function fallbackLocale(): Locale {
  return {
    pane_title: 'Tokens',
    command_description: 'Show the tokens consumed in this session, per model.',
    command_opened: 'Token pane opened.',
    computing: 'Computing…',
    header_session: 'Tokens · this session',
    header_input: 'input',
    header_output: 'output',
    group_claude: 'Claude Code',
    group_opencode: 'OpenCode (from this session)',
    empty_rows: 'No usage yet.',
    cost_session: 'Session cost: $',
    engine_claude: 'Claude ',
    engine_opencode: 'OpenCode ',
    limit_5h: '5h',
    limit_7d: '7d',
    limit_resets: ' (resets ',
    limit_resets_close: ')',
    quota_exhausted: '⚠ quota exhausted ',
    no_variant: 'no variant',
    compaction_suffix: 'compaction ×',
    short_today: 'today ',
    reader_error: 'reader: ',
    weekdays: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
  }
}