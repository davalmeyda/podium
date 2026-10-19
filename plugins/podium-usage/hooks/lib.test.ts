import { expect, test } from 'claude-code/testing'

import {
  buildModelOrder, byRelevance, compactionRows, fmt, inputTokens, label,
  hasOpencodeRun, sessionPrefix, shortDate, tagCommand, totals,
} from './lib'

const SID = '75aff2ef-a6c5-496f-9803-1c14244521a3'
const PREFIX = sessionPrefix(SID)

const enLocale = {
  short_today: 'today ',
  weekdays: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
  no_variant: 'no variant',
  compaction_suffix: 'compaction ×',
} as const

const esLocale = {
  short_today: 'hoy ',
  weekdays: ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'],
  no_variant: 'sin variante',
  compaction_suffix: 'compactación ×',
} as const

test('tags every opencode run without its own session', async () => {
  const one = tagCommand('cd /a && opencode run --auto --agent minimax -m "minimax/MiniMax-M3#none" "$(cat b.txt)" </dev/null > d.txt 2> t.txt', SID, 1)
  expect(one).toContain(`opencode run --session ${PREFIX}`)
  expect(one).toContain('--auto --agent minimax')

  const two = tagCommand('opencode run --agent sol -m x "$(cat a)" > a 2> b; opencode run --agent luna -m y "$(cat b)" > c 2> d', SID, 1)
  const ids = two.match(/--session (\S+)/g) ?? []
  expect(ids.length).toBe(2)
  expect(ids[0]).not.toBe(ids[1])
})

test('respects commands with their own session and ignores others', async () => {
  for (const command of [
    'opencode run -s ses_abc "hello"',
    'opencode run --continue "hello"',
    'opencode run --session=ses_x "hello"',
    'echo opencode runner',
    'ls && opencode --version',
  ]) {
    expect(tagCommand(command, SID, 1)).toBe(command)
  }
  expect(hasOpencodeRun('echo opencode runner')).toBe(false)
  expect(hasOpencodeRun('cd x && opencode run "a"')).toBe(true)
})

test('sums compactions per model', async () => {
  const rows = compactionRows([
    { model: 'claude-opus-5-5', at: 1, in: 10, out: 5, cacheRead: 100, cacheWrite: 0 },
    { model: 'claude-opus-5-5', at: 2, in: 20, out: 5, cacheRead: 0, cacheWrite: 7 },
  ])
  expect(rows.length).toBe(1)
  expect(rows[0]?.in).toBe(30)
  expect(rows[0]?.n).toBe(2)
  expect(label(rows[0]!, enLocale)).toBe('opus-5-5 compaction ×2')
})

test('the hook rewrites Bash before it executes', async ($, on) => {
  let seen = ''
  on('session.id', () => ({ value: SID }))
  on('clock.now', () => ({ value: 1_792_354_000_000 }))
  on('tool.call', { tool: 'Bash' }, ($, e) => {
    seen = e.command
    return { result: 'ok', text: 'ok' }
  })
  await $.tool.call({ tool: 'Bash', command: 'opencode run --agent luna -m "openai/gpt-6-luna#high" "hello"' })
  expect(seen).toMatch(/^opencode run --session ses_cc75aff2efa6c5496f98031c14244521a3x\w+ --agent luna/)
})

test('inputTokens excludes cache re-reads and dates are short', async () => {
  const row = { engine: 'claude', model: 'claude-opus-5-5', variant: '', in: 100, out: 50, cacheRead: 9_000_000, cacheWrite: 900, n: 1, quotaAt: null } as const
  expect(inputTokens(row)).toBe(1000)
  expect(totals([row, row])).toEqual({ inputTokens: 2000, outputTokens: 100 })
  const now = new Date(2026, 9, 18, 15, 0).getTime()
  expect(shortDate(new Date(2026, 9, 18, 19, 50).getTime(), now, enLocale)).toBe('today 19:50')
  expect(shortDate(new Date(2026, 9, 22, 11, 0).getTime(), now, enLocale)).toBe('Thu 22 11:00')
})

test('sorts by model and variant relevance; compactions go last', async () => {
  const row = (engine: 'claude' | 'opencode' | 'compact', model: string, variant = '') =>
    ({ engine, model, variant, in: 0, out: 1, cacheRead: 0, cacheWrite: 0, n: 1, quotaAt: null })
  const claude = byRelevance([
    row('claude', 'claude-haiku-5-5'), row('compact', 'claude-opus-5-5'), row('claude', 'claude-fable-5'),
    row('claude', 'claude-sonnet-5-5'), row('claude', 'claude-opus-5-5'),
  ], [])
  expect(claude.map(r => `${r.engine}:${r.model}`)).toEqual([
    'claude:claude-opus-5-5', 'claude:claude-sonnet-5-5', 'claude:claude-haiku-5-5', 'claude:claude-fable-5', 'compact:claude-opus-5-5',
  ])
  const oc = byRelevance([
    row('opencode', 'minimax/MiniMax-M3', 'none'), row('opencode', 'kimi/k3', ''), row('opencode', 'openai/gpt-6-luna', 'high'),
    row('opencode', 'minimax/MiniMax-M3', 'thinking'), row('opencode', 'openai/gpt-6.1-sol', 'high'),
    row('opencode', 'openai/gpt-6.1-sol', ''), row('opencode', 'openai/gpt-6.1-sol', 'xhigh'),
  ], [])
  expect(oc.map(r => `${r.model}#${r.variant}`)).toEqual([
    'openai/gpt-6.1-sol#xhigh', 'openai/gpt-6.1-sol#high', 'openai/gpt-6.1-sol#', 'openai/gpt-6-luna#high',
    'minimax/MiniMax-M3#thinking', 'minimax/MiniMax-M3#none', 'kimi/k3#',
  ])
})

test('model_order from config drives relevance', async () => {
  const row = (model: string, variant = '') =>
    ({ engine: 'opencode', model, variant, in: 0, out: 1, cacheRead: 0, cacheWrite: 0, n: 1, quotaAt: null }) as const
  // Move haiku above opus; everything not matched stays after the matched list.
  const order = ['haiku', 'opus']
  const sorted = byRelevance([row('claude-opus-5-5'), row('claude-haiku-5-5'), row('kimi/k3')], order).map(r => r.model)
  expect(sorted).toEqual(['claude-haiku-5-5', 'claude-opus-5-5', 'kimi/k3'])
})

test('buildModelOrder compiles fragments and falls back on bad input', () => {
  const compiled = buildModelOrder(['opus', 'sonnet'])
  expect(compiled.length).toBe(2)
  expect(compiled[0]!.test('claude-opus-5-5')).toBe(true)
  expect(compiled[1]!.test('sonnet-5')).toBe(true)

  // Invalid regex fragment is skipped, valid ones kept.
  const partial = buildModelOrder(['opus', '[unbalanced'])
  expect(partial.length).toBe(1)

  // Empty input → default order (length > 0).
  const def = buildModelOrder([])
  expect(def.length).toBeGreaterThan(0)
  expect(def[0]!.test('claude-opus')).toBe(true)
})

test('locale switching changes shortDate weekday names', () => {
  const now = new Date(2026, 9, 18, 15, 0).getTime() // Sun 18 Oct 2026
  // 22 Oct 2026 → Thu (English) / jue (Spanish)
  const at = new Date(2026, 9, 22, 11, 0).getTime()
  expect(shortDate(at, now, enLocale)).toBe('Thu 22 11:00')
  expect(shortDate(at, now, esLocale)).toBe('jue 22 11:00')
  // Same-day uses short_today in either language.
  expect(shortDate(new Date(2026, 9, 18, 19, 50).getTime(), now, enLocale)).toBe('today 19:50')
  expect(shortDate(new Date(2026, 9, 18, 19, 50).getTime(), now, esLocale)).toBe('hoy 19:50')
})

test('locale switching changes the label suffix', () => {
  const compact = { engine: 'compact', model: 'claude-opus-5-5', variant: '', in: 0, out: 1, cacheRead: 0, cacheWrite: 0, n: 2, quotaAt: null } as const
  expect(label(compact, enLocale)).toBe('opus-5-5 compaction ×2')
  expect(label(compact, esLocale)).toBe('opus-5-5 compactación ×2')
  const oc = { engine: 'opencode', model: 'minimax/MiniMax-M3', variant: '', in: 0, out: 1, cacheRead: 0, cacheWrite: 0, n: 1, quotaAt: null } as const
  expect(label(oc, enLocale)).toBe('MiniMax-M3 #no variant')
  expect(label(oc, esLocale)).toBe('MiniMax-M3 #sin variante')
})

test('fmt formats token counts', () => {
  expect(fmt(0)).toBe('0')
  expect(fmt(500)).toBe('500')
  expect(fmt(1500)).toBe('1.5K')
  expect(fmt(9999)).toBe('10.0K')
  expect(fmt(12_345)).toBe('12K')
  expect(fmt(1_500_000)).toBe('1.50M')
  expect(fmt(12_500_000)).toBe('12.5M')
})