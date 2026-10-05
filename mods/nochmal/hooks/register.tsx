import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { NochmalCard, NochmalDnaRow, NochmalFeedback, NochmalScene } from '../types'

// The learner's state belongs to the DeutschLoop engine: this mod reads it through the
// CLI, and only grade / vocab-grade change it, so the engine's own rules still hold
// (no early reviews, no reused prompts, no hinted passes).

// Theme keys rather than raw colours, so the card reads in light and dark themes alike.
const TITLE = 'suggestion'
const BORDER = 'inactive'
const TONES = { pass: 'success', fail: 'error', info: undefined, error: 'warning' } as const
// Cards a former version wrote are dropped when the mod loads.
const CARD_WRITER = 'nochmal-2'
const WAIT_MS = 12_000 // a turn this long gets a card
const STATUS_EVERY_MS = 60_000
const FEEDBACK_MS = 45_000
const LADDER = 6
const PYTHONS = [['python'], ['python3'], ['py', '-3']]
const DAYS = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa']
const LATER = /^(später|spaeter|skip|weg)$/i
const DNA_PANE = 'fehlerdna'
const SCENE_PANE = 'szene'
const ENGINE_CALL = /deutsch_(loop|dna)\.py/
const SCENE_CALL = /\b(roleplay-start|speak|mission-start|roleplay-turn|roleplay-stop|roleplay-finish)\b/
const RECORD_CALL = /\b(record|observe|coach|grade|vocab-grade|undo|forget|merge|rename)\b/
const ENDED_PANE_MS = 20_000
// What Hilfe sends: the tutor answers in role, and the mod makes sure the hint is saved as help.
const HELP_PROMPT =
  'Hilfe-Knopf: Ich komme in der Szene nicht weiter. Gib mir als Partner einen kleinen Hinweis, keinen ' +
  'fertigen Satz, und bleib in der Rolle. Diese Bitte ist kein eigener Zug der Szene.'

const card = atom({ plugin: 'nochmal', key: 'card' } as const, null)
const isShown = atom({ plugin: 'nochmal', key: 'isShown' } as const, false)
const isJudging = atom({ plugin: 'nochmal', key: 'isJudging' } as const, false)
const feedback = atom({ plugin: 'nochmal', key: 'feedback' } as const, null)
const dna = atom({ plugin: 'nochmal', key: 'dna' } as const, null)
const scene = atom({ plugin: 'nochmal', key: 'scene' } as const, null)

type Cli = { ok: true; data: any } | { ok: false; error: string }
type Raw = { ok: true; stdout: string } | { ok: false; error: string }
type Verdict = { verdict: 'pass' | 'fail' | 'missing'; correction: string; note: string }

const SITUATION_SYSTEM =
  'You write practice tasks for DeutschLoop, a German tutor. Each task is a short everyday situation ' +
  'that makes the learner write one German sentence. Reply with the task text only, with no quotation ' +
  'marks, labels, or explanations.'

const JUDGE_SYSTEM =
  'You grade one review answer for DeutschLoop, a German tutor. Judge only the target; never invent ' +
  'errors. Reply with one JSON object and nothing else.'

// Background work outlives the hook that started it; a failure there only skips that step.
const quiet = () => undefined

const join = (first: string, ...rest: string[]) =>
  [first.replace(/[\\/]+$/, ''), ...rest.map(part => part.replace(/^[\\/]+|[\\/]+$/g, ''))].join('/')

const parseJson = (text: string): any => {
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start < 0 || end < start) return null
  try {
    return JSON.parse(text.slice(start, end + 1))
  } catch {
    return null
  }
}

/** The card's back: `Am 21.08.: „Ich warte dich.“ · Heute: „Ich warte auf dich.“ ✓`. */
const story = (current: NochmalCard, sentence: string, isPass: boolean, nowMs: number): string | undefined => {
  if (current.kind !== 'pattern' || !current.example) return undefined
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(current.example.seenAtLocal ?? '')
  const year = match && Number(match[1]) !== new Date(nowMs).getUTCFullYear() ? match[1] : ''
  const then = match ? `Am ${match[3]}.${match[2]}.${year}` : 'Früher'
  return `${then}: „${current.example.original}“ · Heute: „${sentence}“ ${isPass ? '✓' : '✗'}`
}

/** `2026-10-09T21:38:00+02:00` → `Fr 21:38`, `morgen 21:38`, or `23.10.` further out. */
const when = (iso: string | null | undefined, nowMs: number): string => {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}).*?([+-])(\d{2}):(\d{2})$/.exec(iso ?? '')
  if (!match) return ''
  const [, year, month, day, hours, minutes, sign, offsetHours, offsetMinutes] = match
  const offset = (sign === '-' ? -1 : 1) * (Number(offsetHours) * 60 + Number(offsetMinutes)) * 60_000
  const local = new Date(nowMs + offset)
  const today = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate())
  const target = Date.UTC(Number(year), Number(month) - 1, Number(day))
  const days = Math.round((target - today) / 86_400_000)
  const time = `${hours}:${minutes}`
  if (days <= 0) return `heute ${time}`
  if (days === 1) return `morgen ${time}`
  if (days < 7) return `${DAYS[new Date(target).getUTCDay()]} ${time}`
  return `${day}.${month}.`
}

// Module state; a hot reload starts it over, the drawn values live in $.state.
let located: { python: string[]; script: string } | null | undefined
let problem = ''
let language = 'en'
let level = ''
let dueNow = 0
let statusAt = 0
let isTurnRunning = false
let turnTimer: { cancel: () => void } | undefined
let feedbackTimer: { cancel: () => void } | undefined
let ticker: { cancel: () => void } | undefined
let sceneCloser: { cancel: () => void } | undefined
let frames: Record<string, { title?: string; learner_goal?: string }> | undefined

const ladder = (step: number) => '▰'.repeat(Math.min(step, LADDER)) + '▱'.repeat(Math.max(0, LADDER - step))

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`

const fit = (text: string, width: number) =>
  text.length > width ? `${text.slice(0, width - 1)}…` : text.padEnd(width)

/** One ladder row: `mit + Dativ   ▰▰▱▱▱▱   2× ✗  Do 12:00`. */
const dnaRowText = (row: NochmalDnaRow, labelWidth: number, nowMs: number) => {
  const state = row.status === 'mastered' ? '★ gemeistert' : row.isDue ? 'jetzt fällig' : when(row.nextLocal, nowMs)
  return `${fit(row.label, labelWidth)} ${ladder(row.step)}  ${String(row.wrong).padStart(2)}× ✗  ${state}`
}

async function userHome($: EngineInterface) {
  return ((await $.env.get('USERPROFILE')) || (await $.env.get('HOME')) || '').replace(/\\/g, '/')
}

/** The engine's own choice of folder: the setting, else ~/.deutschloop, else the older ~/.deutschdna. */
async function stateHome($: EngineInterface) {
  const home = await userHome($)
  const configured = (await $.env.get('DEUTSCHLOOP_HOME')) || (await $.env.get('DEUTSCHDNA_HOME'))
  if (configured) return configured.replace(/^~(?=$|[\\/])/, home)
  const current = join(home, '.deutschloop')
  const legacy = join(home, '.deutschdna')
  return !(await $.fs.exists(current)) && (await $.fs.exists(legacy)) ? legacy : current
}

async function run($: EngineInterface, argv: string[]) {
  try {
    return await $.process.run(argv, { timeoutMs: 20_000 })
  } catch {
    return null
  }
}

/** Newest first: `2.10.0` before `2.9.1`. */
const byVersion = (a: string, b: string) => {
  const parts = (version: string) => version.split('.').map(part => Number.parseInt(part, 10) || 0)
  const [left, right] = [parts(a), parts(b)]
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const order = (right[index] ?? 0) - (left[index] ?? 0)
    if (order) return order
  }
  return 0
}

/**
 * The engine this companion drives: the repository it sits in (`mods/nochmal`), the session's
 * checkout, a cloned skill, the installed DeutschLoop plugin, or the marketplace's own clone.
 */
async function locate($: EngineInterface) {
  if (located !== undefined) return located
  const home = await userHome($)
  const plugins = join(home, '.claude', 'plugins')
  const scripts = [
    join($.plugin.root, '..', '..', 'scripts', 'deutsch_loop.py'),
    join(await $.session.cwd(), 'scripts', 'deutsch_loop.py'),
    join(home, '.claude', 'skills', 'deutsch-loop', 'scripts', 'deutsch_loop.py'),
  ]
  try {
    const cache = join(plugins, 'cache', 'deutsch-loop', 'deutsch-loop')
    const versions = (await $.fs.list(cache)).filter(entry => entry.kind === 'directory').map(entry => entry.name)
    scripts.push(...versions.sort(byVersion).map(version => join(cache, version, 'scripts', 'deutsch_loop.py')))
  } catch {
    // No installed DeutschLoop plugin.
  }
  scripts.push(join(plugins, 'marketplaces', 'deutsch-loop', 'scripts', 'deutsch_loop.py'))
  for (const script of scripts) {
    if (!(await $.fs.exists(script))) continue
    for (const python of PYTHONS) {
      const result = await run($, [...python, script, '--help'])
      if (result?.exitCode === 0) return (located = { python, script })
    }
  }
  return (located = null)
}

async function engineRun($: EngineInterface, args: string[]): Promise<Raw> {
  const engine = await locate($)
  if (!engine) return { ok: false, error: 'DeutschLoop oder Python wurde nicht gefunden.' }
  const home = await stateHome($)
  // Every engine command locks, and so creates, its folder: never start a learner's memory here.
  if (!(await $.fs.exists(home))) return { ok: false, error: 'Noch keine FehlerDNA: übe zuerst mit /deutsch-loop.' }
  const result = await run($, [...engine.python, engine.script, '--home', home, ...args])
  if (!result) return { ok: false, error: 'Python konnte nicht gestartet werden.' }
  if (result.exitCode === 0) return { ok: true, stdout: result.stdout }
  const data = parseJson(result.stderr || result.stdout)
  return { ok: false, error: String(data?.error ?? (result.stderr || result.stdout).trim().slice(0, 200)) }
}

async function cli($: EngineInterface, args: string[]): Promise<Cli> {
  const ran = await engineRun($, args)
  if (!ran.ok) return ran
  const data = parseJson(ran.stdout)
  return data ? { ok: true, data } : { ok: false, error: 'Die Antwort von DeutschLoop war leer.' }
}

async function refreshStatus($: EngineInterface) {
  statusAt = await $.clock.now()
  const recap = await cli($, ['recap'])
  if (!recap.ok) {
    problem = recap.error
    dueNow = 0
    $.ui.status(undefined)
    return
  }
  problem = ''
  const data = recap.data
  language = data.profile?.explanation_language || data.onboarding?.explanation_language || data.profile?.native_language || 'en'
  level = data.profile?.level && data.profile.level !== 'unspecified' ? data.profile.level : ''
  const patterns = Number(data.due_now ?? 0)
  const words = Number(data.vocabulary?.due_now ?? 0)
  dueNow = patterns + words
  const due = []
  if (patterns) due.push(`${patterns} Muster`)
  if (words) due.push(`${words} ${words === 1 ? 'Wort' : 'Wörter'}`)
  const parts = ['FehlerDNA', due.length ? `fällig: ${due.join(', ')}` : 'nichts fällig']
  if (data.streak_days) parts.push(`${data.streak_days} ${data.streak_days === 1 ? 'Tag' : 'Tage'} in Folge`)
  $.ui.status(parts.join(' · '))
}

async function complete($: EngineInterface, model: string, system: string, prompt: string, maxTokens: number) {
  try {
    const reply = await $.model.complete({ model, system, prompt, maxTokens, timeoutMs: 60_000 })
    return reply.isAnswered ? reply.text.trim() : null
  } catch {
    return null
  }
}

async function writeSituation($: EngineInterface, task: string) {
  const text = await complete($, 'sonnet', SITUATION_SYSTEM, task, 300)
  return text ? text.replace(/^["„“”']+|["„“”']+$/g, '').trim() : null
}

/** The first due pattern, else the first due word, with a situation it has not been asked in. */
async function prepareCard($: EngineInterface): Promise<NochmalCard | null> {
  const ask =
    `Write one new situation in the language with ISO code "${language}": at most two short sentences ` +
    'that end by telling the learner what to say in German. Do not write the German answer.'
  const patterns = await cli($, ['due', '--limit', '1'])
  if (patterns.ok && patterns.data.count > 0) {
    const mistake = patterns.data.mistakes[0]
    // The first mistake: the card's back sets it beside today's sentence.
    const seen = mistake.first_example ?? mistake.last_example
    const example = seen
      ? { original: String(seen.original), corrected: String(seen.corrected), seenAtLocal: seen.seen_at_local ?? null }
      : null
    const situation = await writeSituation($, [
      `Pattern to practise: ${mistake.label}`,
      `Rule: ${mistake.rule}`,
      example ? `Earlier mistake: „${example.original}" → „${example.corrected}"` : '',
      `Learner level: ${level || 'unknown'}`,
      '',
      `${ask} The answer must naturally need this pattern. When the pattern is about a particular word ` +
        '(a noun and its gender, a verb and its preposition, a fixed phrase), the answer must use that word. ' +
        'Change the people and the place of the earlier mistake, and do not name the rule. You may add one ' +
        'German noun in parentheses if the learner might not know it.',
    ].join('\n'))
    if (!situation) return null
    return {
      writer: CARD_WRITER, kind: 'pattern', id: mistake.id, target: mistake.label, meaning: null, rule: mistake.rule ?? null,
      example, situation, prompt: situation, language,
    }
  }
  const words = await cli($, ['vocab-due', '--limit', '1'])
  if (words.ok && words.data.count > 0) {
    const word = words.data.words[0]
    const earlier: string[] = word.recent_prompts ?? []
    const situation = await writeSituation($, [
      `Word to practise: ${word.term} (${word.meaning})`,
      `Earlier tasks for this word: ${earlier.length ? earlier.join(' | ') : 'none'}`,
      `Learner level: ${level || 'unknown'}`,
      '',
      `${ask} The answer must use "${word.term}". Do not repeat an earlier task.`,
    ].join('\n'))
    if (!situation) return null
    return {
      writer: CARD_WRITER, kind: 'word', id: word.id, target: word.term, meaning: word.meaning, rule: null, example: null,
      situation, prompt: `${word.term} (${word.meaning}): ${situation}`, language,
    }
  }
  return null
}

async function judge($: EngineInterface, current: NochmalCard, sentence: string): Promise<Verdict | null> {
  const target =
    current.kind === 'pattern'
      ? `the pattern "${current.target}" (rule: ${current.rule})`
      : `the word "${current.target}" (${current.meaning})`
  const text = await complete($, 'sonnet', JUDGE_SYSTEM, [
    `Target: ${target}`,
    current.example ? `The learner's earlier mistake: „${current.example.original}" → „${current.example.corrected}"` : '',
    `Task: ${current.prompt}`,
    `Learner's answer: ${sentence}`,
    '',
    'verdict: "pass" when the answer uses the target and that part is correct German; "fail" when it uses ' +
      'the target but gets that part wrong; "missing" when it does not use the target or does not answer the task.',
    'When the target is about one particular word (a noun and its gender, a verb and its preposition, a fixed ' +
      'phrase), an answer without that word is "missing". Other mistakes never make a "fail": name them in the note.',
    'correction: for "fail", the learner\'s sentence with the fewest changes that make it correct; otherwise "".',
    `note: one short sentence in the language with ISO code "${current.language}" that says what was right ` +
      'or what to fix, and names any other mistake briefly.',
    '',
    '{"verdict": "...", "correction": "...", "note": "..."}',
  ].join('\n'), 400)
  const verdict = text ? parseJson(text) : null
  if (!verdict || !['pass', 'fail', 'missing'].includes(verdict.verdict)) return null
  return { verdict: verdict.verdict, correction: String(verdict.correction ?? '').trim(), note: String(verdict.note ?? '').trim() }
}

async function tell($: EngineInterface, note: NochmalFeedback) {
  await update($, feedback, () => note)
  feedbackTimer?.cancel()
  feedbackTimer = $.clock.after(FEEDBACK_MS, () => void update($, feedback, () => null).catch(quiet))
  return note
}

async function answer($: EngineInterface, sentence: string): Promise<NochmalFeedback> {
  const current = await read($, card)
  if (!current) return tell($, { tone: 'info', text: 'Keine Karte offen. /nochmal holt eine.' })
  if (await read($, isJudging)) return { tone: 'info', text: 'Die Antwort wird schon geprüft.' }
  await update($, isJudging, () => true)
  try {
    const verdict = await judge($, current, sentence)
    if (!verdict) return tell($, { tone: 'error', text: 'Die Prüfung hat nicht geklappt. Versuch es gleich noch einmal.' })
    if (verdict.verdict === 'missing') {
      return tell($, { tone: 'info', text: `${verdict.note} Gesucht: ${current.target}.`.trim() })
    }
    const args = [current.kind === 'pattern' ? 'grade' : 'vocab-grade', current.id, '--result', verdict.verdict,
      '--prompt', current.prompt, '--answer', sentence]
    if (verdict.verdict === 'fail') args.push('--correction', verdict.correction || sentence)
    const saved = await cli($, args)
    // A card the engine refuses (no longer due, a prompt it has seen) is not offered again.
    await update($, card, () => null)
    await update($, isShown, () => false)
    if (!saved.ok) return tell($, { tone: 'error', text: `Nicht gespeichert: ${saved.error}` })
    if (saved.data.status === 'duplicate') return tell($, { tone: 'info', text: 'Diese Antwort war schon gespeichert.' })
    const item = saved.data.mistake ?? saved.data.word ?? {}
    const nowMs = await $.clock.now()
    await refreshStatus($)
    void refreshDnaIfOpen($).catch(quiet)
    if (verdict.verdict === 'fail') {
      return tell($, {
        tone: 'fail',
        text: `✗ ${verdict.correction} ${verdict.note} Kommt ${when(item.next_review_local, nowMs)} wieder.`,
        story: story(current, sentence, false, nowMs),
      })
    }
    const progress =
      item.status === 'mastered'
        ? 'Gemeistert!'
        : `Stufe ${item.review_step ?? '?'}/${LADDER} · wieder ${when(item.next_review_local, nowMs)}`
    return tell($, { tone: 'pass', text: `✓ Richtig. ${verdict.note} ${progress}`, story: story(current, sentence, true, nowMs) })
  } finally {
    await update($, isJudging, () => false)
  }
}

async function refreshDna($: EngineInterface) {
  const listed = await cli($, ['list', '--status', 'all'])
  if (!listed.ok) return listed.error
  const nowMs = await $.clock.now()
  const rows: NochmalDnaRow[] = (listed.data.mistakes ?? []).map((mistake: any) => {
    const nextLocal = mistake.next_review_local ?? null
    return {
      id: String(mistake.id), label: String(mistake.label ?? mistake.pattern), status: String(mistake.status),
      step: Number(mistake.review_step ?? 0), wrong: Number(mistake.occurrences ?? 0), right: Number(mistake.right ?? 0),
      nextLocal, isDue: mistake.status === 'active' && nextLocal !== null && Date.parse(nextLocal) <= nowMs,
    }
  })
  // Due first, then by the next review, the mastered ones last.
  const rank = (row: NochmalDnaRow) => (row.isDue ? 0 : row.status === 'mastered' ? 2 : 1)
  rows.sort((a, b) => rank(a) - rank(b) || (a.nextLocal ?? '').localeCompare(b.nextLocal ?? '') || a.label.localeCompare(b.label))
  const mastered = rows.filter(row => row.status === 'mastered').length
  await update($, dna, view => ({ rows, mastered, story: view?.story ?? null }))
  return ''
}

async function refreshDnaIfOpen($: EngineInterface) {
  if ((await $.ui.panes()).some(pane => pane.id === DNA_PANE)) await refreshDna($)
}

async function openStory($: EngineInterface, id: string, label: string) {
  const shown = await engineRun($, ['show', id, '--format', 'text'])
  const text = shown.ok ? shown.stdout.trim() : `Die Geschichte konnte nicht geladen werden: ${shown.error}`
  await update($, dna, view => (view ? { ...view, story: { id, label, text } } : view))
}

/** A scenario's title and goal from the engine's catalog, for a scene whose start the mod did not see. */
async function scenarioFrame($: EngineInterface, scenario: string) {
  if (!frames) {
    const listed = await cli($, ['scenarios'])
    const found: Record<string, { title?: string; learner_goal?: string }> = {}
    for (const frame of listed.ok ? listed.data.scenarios ?? [] : []) found[String(frame.id)] = frame
    frames = found
  }
  return frames[scenario] ?? null
}

/** Follows the engine's active scene; `output` is a scene command's JSON, which carries the scene's contract. */
async function refreshScene($: EngineInterface, output?: string) {
  const recap = await cli($, ['recap'])
  if (!recap.ok) return
  const active = recap.data.active_roleplay
  const held = await read($, scene)
  const nowMs = await $.clock.now()
  if (!active || active.status !== 'active') {
    if (held?.isActive) {
      const endedSeconds = Number(active?.elapsed_seconds ?? Math.max(0, Math.floor((nowMs - held.startedAtMs) / 1000)))
      await update($, scene, view => (view ? { ...view, isActive: false, isHelpPending: false, endedSeconds } : view))
      ticker?.cancel()
      ticker = undefined
      sceneCloser?.cancel()
      sceneCloser = $.clock.after(ENDED_PANE_MS, () => void closeScene($).catch(quiet))
    }
    return
  }
  const shown = await cli($, ['roleplay-show', String(active.session_id)])
  const utterances: any[] = shown.ok ? shown.data.session?.utterances ?? [] : []
  const same = held && held.id === active.session_id ? held : null
  const contract = parseJson(output ?? '')?.contract
  const frame = contract || same ? null : await scenarioFrame($, String(active.scenario))
  const title = String(contract?.title ?? same?.title ?? frame?.title ?? active.scenario)
  const view: NochmalScene = {
    id: String(active.session_id),
    title,
    role: contract?.assistant_role ?? same?.role ?? null,
    goal: contract?.learner_goal ?? same?.goal ?? frame?.learner_goal ?? null,
    personalGoal: contract?.personal_goal ?? same?.personalGoal ?? null,
    startedAtMs: Date.parse(active.started_at_local) || nowMs,
    targetSeconds: Number(active.target_seconds ?? 300),
    learnerTurns: Number(active.learner_turns ?? 0),
    suggestedTurns: contract?.suggested_turns ?? same?.suggestedTurns ?? null,
    helps: utterances.filter(turn => turn.support && turn.support !== 'none').length,
    shouldClose: Boolean(active.should_close),
    isActive: true,
    endedSeconds: null,
    isHelpPending: same?.isHelpPending ?? false,
  }
  await update($, scene, () => view)
  sceneCloser?.cancel()
  // The clock in the pane runs on its own: one redraw a second.
  if (!ticker) ticker = $.clock.every(1000, () => $.ui.invalidate('ui.render'))
  if (!(await $.ui.panes()).some(pane => pane.id === SCENE_PANE)) {
    const opened = await $.ui.open({ id: SCENE_PANE, title: `Szene · ${title}` })
    if (!opened.isPlaced) $.ui.toast('Eine Szene läuft: /szene zeigt das Panel.')
  }
}

async function closeScene($: EngineInterface) {
  const held = await read($, scene)
  if (held?.isActive) return
  await $.ui.close({ id: SCENE_PANE })
  await update($, scene, () => null)
}

async function askForHelp($: EngineInterface) {
  const held = await read($, scene)
  if (!held?.isActive || held.isHelpPending) return
  await update($, scene, view => (view ? { ...view, isHelpPending: true } : view))
  await $.prompt.submit({ text: HELP_PROMPT })
}

/**
 * Watches the tutor's own engine calls. After Hilfe, the partner turn that answers it is saved
 * with `--support hint` even when the tutor leaves the flag out, so help is never counted as
 * unaided; a turn the tutor marked itself (`shown`, for a full answer) keeps its mark.
 */
async function engineCall($: EngineInterface, e: any, next: (call: any) => Promise<any>) {
  const command = String(e.command ?? '')
  if (!ENGINE_CALL.test(command)) return next(e)
  let call = e
  const held = await read($, scene)
  if (held?.isHelpPending && /roleplay-turn/.test(command) && /--speaker[= ]+["']?partner/.test(command)) {
    if (!/--support/.test(command)) call = { ...e, command: command.replace(/(roleplay-turn\s+\S+)/, '$1 --support hint') }
    await update($, scene, view => (view ? { ...view, isHelpPending: false } : view))
  }
  const ran = await next(call)
  const output = typeof ran?.text === 'string' ? ran.text : ran?.result?.stdout
  if (SCENE_CALL.test(command)) await refreshScene($, output)
  if (RECORD_CALL.test(command) || SCENE_CALL.test(command)) {
    void refreshDnaIfOpen($).catch(quiet)
    void refreshStatus($).catch(quiet)
  }
  return ran
}

async function showDuringTurn($: EngineInterface) {
  if (!isTurnRunning) return
  if (!(await read($, card))) {
    if (!dueNow) return
    const prepared = await prepareCard($)
    if (!prepared) return
    await update($, card, () => prepared)
    // A card prepared too late waits for the next long turn.
    if (!isTurnRunning) return
  }
  await update($, isShown, () => true)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'nochmal',
      description: 'Practise a due FehlerDNA card (DeutschLoop); works while Claude is busy',
      argumentHint: '[German sentence | später]',
      immediate: true,
    })
    await $.command.register({
      name: 'fehlerdna',
      description: 'Your FehlerDNA as a live pane: every pattern on its 1-3-7-14-30-60 ladder (DeutschLoop)',
      immediate: true,
    })
    await $.command.register({
      name: 'szene',
      description: 'Show the running roleplay scene: role, goal, turns, time, and a Hilfe button (DeutschLoop)',
      immediate: true,
    })
    const held = await read($, card)
    if (held && held.writer !== CARD_WRITER) {
      await update($, card, () => null)
      await update($, isShown, () => false)
    }
    void refreshStatus($).catch(quiet)

    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    isTurnRunning = true
    turnTimer?.cancel()
    // A tutoring turn or a running scene needs no second card.
    const isPlaying = (await read($, scene))?.isActive
    if (!isPlaying && !/deutsch-loop|deutsch-dna/i.test(e.text)) {
      turnTimer = $.clock.after(WAIT_MS, () => void showDuringTurn($).catch(quiet))
    }

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId) return next(e)
    isTurnRunning = false
    turnTimer?.cancel()
    if ((await $.clock.now()) - statusAt > STATUS_EVERY_MS) void refreshStatus($).catch(quiet)

    return next(e)
  })

  on('command.run', { command: 'nochmal' }, async ($, e) => {
    const text = e.args.trim()
    if (LATER.test(text)) {
      await update($, isShown, () => false)
      return { text: 'Nochmal: später.' }
    }
    if (text) {
      const note = await answer($, text)
      return { text: `Nochmal: ${note.text}${note.story ? `\n${note.story}` : ''}` }
    }
    let current = await read($, card)
    if (!current) {
      await refreshStatus($)
      if (problem) return { text: `Nochmal: ${problem}` }
      current = dueNow ? await prepareCard($) : null
      if (!current) return { text: 'Nochmal: Gerade ist nichts fällig.' }
      const prepared = current
      await update($, card, () => prepared)
    }
    await update($, isShown, () => true)
    return { text: `Nochmal: ${current.target}. Die Karte steht über der Eingabe.` }
  })

  on('tool.call', { tool: 'Bash' }, ($, e, next) => engineCall($, e, next))
  on('tool.call', { tool: 'PowerShell' }, ($, e, next) => engineCall($, e, next))

  on('command.run', { command: 'fehlerdna' }, async $ => {
    const problemText = await refreshDna($)
    if (problemText) return { text: `FehlerDNA: ${problemText}` }
    await update($, dna, view => (view ? { ...view, story: null } : view))
    await $.ui.open({ id: DNA_PANE, title: 'FehlerDNA' })
    return { text: 'FehlerDNA: Panel geöffnet.' }
  })

  on('command.run', { command: 'szene' }, async $ => {
    await refreshScene($)
    const held = await read($, scene)
    if (!held) return { text: 'Szene: Gerade läuft keine Szene.' }
    await $.ui.open({ id: SCENE_PANE, title: `Szene · ${held.title}` })
    return { text: `Szene: ${held.title}.` }
  })

  on('ui.render', { component: 'Pane', requestId: DNA_PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const view = await read($, dna)
    if (!view) return <Text dimColor>FehlerDNA wird geladen …</Text>
    if (view.story) {
      return (
        <Box flexDirection="column">
          <Button
            key="back"
            label="← Zurück"
            onPress={() => void update($, dna, held => (held ? { ...held, story: null } : held)).catch(quiet)}
          />
          {view.story.text.split('\n').map(line => <Text wrap="wrap">{line || ' '}</Text>)}
        </Box>
      )
    }
    const nowMs = await $.clock.now()
    const labelWidth = Math.max(12, Math.min(30, (e.props.bodyColumns ?? 60) - 30))
    const rows = view.rows.map(row => (
      <Button
        key={`row:${row.id}`}
        plain
        label={dnaRowText(row, labelWidth, nowMs)}
        variant={row.isDue ? 'primary' : undefined}
        dimColor={row.status === 'mastered' ? true : undefined}
        onPress={() => void openStory($, row.id, row.label).catch(quiet)}
      />
    ))
    return (
      <Box flexDirection="column">
        <Text color={TITLE} bold>{`FehlerDNA · ${view.rows.length} Muster · ${view.mastered} gemeistert`}</Text>
        <Text dimColor wrap="wrap">Stufen ▰: 1 · 3 · 7 · 14 · 30 · 60 Tage. Eine Zeile öffnet ihre Geschichte.</Text>
        {rows.length ? rows : <Text dimColor>Noch keine Muster gespeichert.</Text>}
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: SCENE_PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const view = await read($, scene)
    if (!view) return <Text dimColor>Gerade läuft keine Szene.</Text>
    const nowMs = await $.clock.now()
    const seconds = view.isActive ? Math.max(0, Math.floor((nowMs - view.startedAtMs) / 1000)) : view.endedSeconds ?? 0
    const filled = Math.round(Math.min(1, seconds / Math.max(1, view.targetSeconds)) * 10)
    const turns = `${view.learnerTurns}${view.suggestedTurns ? ` von etwa ${view.suggestedTurns}` : ''}`
    const rows = [<Text color={TITLE} bold wrap="wrap">{view.title}</Text>]
    if (view.role) rows.push(<Text dimColor wrap="wrap">{`Partner: ${view.role}`}</Text>)
    if (view.goal) rows.push(<Text wrap="wrap">{`Ziel: ${view.goal}`}</Text>)
    if (view.personalGoal) rows.push(<Text wrap="wrap">{`Dein Ziel: ${view.personalGoal}`}</Text>)
    rows.push(
      <Text>{`Deine Züge: ${turns}`}</Text>,
      <Text>{`Zeit: ${clock(seconds)} / ${clock(view.targetSeconds)}  ${'█'.repeat(filled)}${'░'.repeat(10 - filled)}`}</Text>,
      <Text dimColor>{`Hilfe: ${view.helps === 0 ? 'noch keine' : `${view.helps}×`}`}</Text>,
    )
    if (view.isActive && view.shouldClose) {
      rows.push(<Text color="warning" wrap="wrap">Die Zeit ist um: noch ein Satz, dann kommt das Feedback.</Text>)
    }
    if (view.isActive) {
      rows.push(
        <Button key="help" label={view.isHelpPending ? 'Hilfe kommt …' : 'Hilfe'} onPress={() => void askForHelp($).catch(quiet)} />,
        <Text dimColor wrap="wrap">Hilfe wird ehrlich gespeichert: der Hinweis zählt als Unterstützung.</Text>,
      )
    } else {
      rows.push(<Text wrap="wrap">Szene beendet. Das Feedback kommt im Chat.</Text>)
    }
    return <Box flexDirection="column">{rows}</Box>
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey || (e.surface !== 'terminal' && e.surface !== 'desktop')) return next(e)
    const current = await read($, card)
    const shown = await read($, isShown)
    const note = await read($, feedback)
    const busy = await read($, isJudging)
    if (!(current && shown) && !note) return next(e)

    const { Box, Button, Input, Text } = $.ui.resolve(e)
    const rows = []
    if (note) rows.push(<Text color={TONES[note.tone]} wrap="wrap">{note.text}</Text>)
    if (note?.story) rows.push(<Text wrap="wrap">{note.story}</Text>)
    if (current && shown) {
      const target = current.kind === 'word' ? `${current.target} (${current.meaning})` : current.target
      rows.push(
        <Box key="title" gap={1}>
          <Text color={TITLE} bold>Nochmal</Text>
          <Text dimColor wrap="truncate-end">{`· ${target}`}</Text>
        </Box>,
        <Text wrap="wrap">{current.situation}</Text>,
        busy ? (
          <Text dimColor>Wird geprüft …</Text>
        ) : (
          <Input
            key="answer"
            placeholder="Deine Antwort auf Deutsch"
            submitLabel="prüfen"
            onSubmit={value => {
              if (value.trim()) void answer($, value.trim()).catch(quiet)
            }}
          />
        ),
        <Box key="actions" gap={2}>
          <Button key="later" label="Später" onPress={() => void update($, isShown, () => false).catch(quiet)} />
          <Text dimColor wrap="truncate-end">
            {`${e.surface === 'terminal' ? 'ctrl+x tab' : 'Klick'}: antworten · /nochmal <Satz>`}
          </Text>
        </Box>,
      )
    }

    return (
      <Box flexDirection="column" borderStyle="round" borderColor={BORDER} paddingX={1}>
        {rows}
      </Box>
    )
  })
}
