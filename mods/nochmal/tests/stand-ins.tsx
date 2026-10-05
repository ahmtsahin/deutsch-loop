import { mock } from 'claude-code/testing'
import type { On } from 'claude-code'

// Nothing stands beneath a plugin in a test: these hooks play the engine, the DeutschLoop
// CLI, the tools, and the models, so every flow runs without Python or a model call.

export const CARD = {
  writer: 'nochmal-2', kind: 'pattern', id: 'm_wait', target: 'warten auf + Akkusativ', meaning: null,
  rule: 'warten auf takes the accusative', example: null,
  situation: 'Arkadaşın gecikiyor. Ona istasyonda onu beklediğini söyle.',
  prompt: 'Arkadaşın gecikiyor. Ona istasyonda onu beklediğini söyle.', language: 'tr',
} as const

export const STORY = [
  'warten auf + Akkusativ · Präpositionen · aktiv',
  '',
  '2026-08-21  ✗ Fehler         Ich warte dich. → Ich warte auf dich.',
  '2026-08-22  ✓ Wiederholung   Wir warten auf den Bus.',
].join('\n')

export const SPEAK_OUTPUT = JSON.stringify({
  contract: {
    title: 'Restaurant', assistant_role: 'a waiter in a busy restaurant', suggested_turns: 8, personal_goal: null,
    learner_goal: 'Handle the reservation, order, one special request, and payment.',
  },
  session: { id: 's_1', status: 'active' },
})

export const COMMAND = { origin: { kind: 'composer' as const }, presentation: { isFullscreen: true, columns: 100 } }

const SITE = { scroll: { offset: 0, bodyRows: 12 }, view: {} }

export const BAND = (isWorking: boolean) => ({
  component: 'AbovePrompt' as const,
  props: { hasSurvey: false, isWorking, maxRows: 12, bodyColumns: 80, ...SITE },
})

export const PANE = (requestId: string) => ({
  component: 'Pane' as const,
  requestId,
  props: { title: requestId, isFocused: true, bodyColumns: 70, placement: 'dock' as const, ...SITE },
})

export type Stand = {
  state: Map<string, { value: unknown; version: number }>
  runs: string[][]
  statuses: (string | undefined)[]
  panes: string[]
  prompts: string[]
  /** What the tools were asked to run, rewrites included. */
  commands: string[]
  isPlaying: boolean
  helps: number
  clock: ReturnType<typeof mock.clock>
}

type Verdict = { verdict: string; correction: string; note: string }

export function standIns(on: On, verdict: Verdict = { verdict: 'pass', correction: '', note: 'Akkusativ doğru.' }, hasLearner = true): Stand {
  const stand: Stand = {
    state: new Map(), runs: [], statuses: [], panes: [], prompts: [], commands: [], isPlaying: false, helps: 0,
    clock: mock.clock(on, { now: Date.UTC(2026, 9, 5, 10, 0) }),
  }
  mock.env(on, { USERPROFILE: 'C:\\Users\\test' })
  on('state.get', ($, e) => ({ value: stand.state.get(e.key) ?? { value: undefined, version: 0 } }))
  on('state.set', ($, e) => {
    const held = stand.state.get(e.key) ?? { value: undefined, version: 0 }
    if (e.ifVersion !== undefined && e.ifVersion !== held.version) return { value: { isSet: false, version: held.version } }
    stand.state.set(e.key, { value: e.value, version: held.version + 1 })
    return { value: { isSet: true, version: held.version + 1 } }
  })
  on('ui.render', ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  on('ui.status', ($, e) => {
    stand.statuses.push(e.text)
    return { value: undefined }
  })
  on('ui.open', ($, e) => {
    if (!stand.panes.includes(e.id)) stand.panes.push(e.id)
    return { value: { isPlaced: true } }
  })
  on('ui.close', ($, e) => {
    stand.panes = stand.panes.filter(id => id !== e.id)
    return { value: undefined }
  })
  on('ui.panes', () => ({
    value: stand.panes.map(id => ({ id, title: id, isShown: true, isFocused: false, isPlaced: true })),
  }))
  on('ui.invalidate', () => ({ value: undefined }))
  on('ui.toast', () => ({ value: undefined }))
  on('prompt.submit', ($, e) => {
    stand.prompts.push(e.text)
    return { text: e.text }
  })
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.cwd', () => ({ value: 'C:/work' }))
  on('fs.list', () => ({ deny: 'no such folder' }))
  on('fs.exists', ($, e) => {
    const path = e.path.replace(/\\/g, '/')
    return { value: path.endsWith('/scripts/deutsch_loop.py') || (hasLearner && path === 'C:/Users/test/.deutschloop') }
  })
  on('process.run', ($, e) => {
    const argv = [...e.argv]
    stand.runs.push(argv)
    const command = argv[argv.indexOf('--home') + 2]
    const out = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '' } })
    const json = (data: unknown) => out(JSON.stringify(data))
    if (argv.includes('--help')) return out('usage')
    if (command === 'recap') {
      return json({
        due_now: 1, vocabulary: { due_now: 0 }, streak_days: 17, profile: { explanation_language: 'tr', level: 'B2' },
        active_roleplay: stand.isPlaying
          ? { session_id: 's_1', scenario: 'restaurant', status: 'active', elapsed_seconds: 30, target_seconds: 300,
              learner_turns: 2, should_close: false, started_at_local: '2026-10-05T11:59:30+02:00' }
          : null,
      })
    }
    if (command === 'due') {
      return json({ count: 1, mistakes: [{ id: 'm_wait', label: 'warten auf + Akkusativ', rule: 'warten auf takes the accusative',
        first_example: { original: 'Ich warte dich.', corrected: 'Ich warte auf dich.', seen_at_local: '2026-08-21T10:00:00+02:00' } }] })
    }
    if (command === 'grade') {
      return json({ status: 'reviewed', mistake: { status: 'active', review_step: 1, next_review_local: '2026-10-08T12:00:00+02:00' } })
    }
    if (command === 'list') {
      return json({ count: 3, mistakes: [
        { id: 'm_done', label: '-ung-Wörter sind feminin', status: 'mastered', review_step: 6, occurrences: 1, right: 6, next_review_local: null },
        { id: 'm_later', label: 'mit + Dativ', status: 'active', review_step: 2, occurrences: 2, right: 3, next_review_local: '2026-10-08T12:00:00+02:00' },
        { id: 'm_wait', label: 'warten auf + Akkusativ', status: 'active', review_step: 1, occurrences: 4, right: 1, next_review_local: '2026-10-04T12:00:00+02:00' },
      ] })
    }
    if (command === 'show') return out(STORY)
    if (command === 'roleplay-show') {
      const utterances = Array.from({ length: stand.helps }, (_, index) => ({ id: `t_${index}`, speaker: 'partner', support: 'hint' }))
      return json({ session: { id: 's_1', utterances } })
    }
    return { value: { exitCode: 2, stdout: '', stderr: JSON.stringify({ error: `unexpected ${command}` }) } }
  })
  // The tool beneath the plugin: it runs what it was handed, as the tutor's shell would.
  on('tool.call', ($, e) => {
    const command = String((e as { command?: string }).command ?? '')
    stand.commands.push(command)
    if (/\bspeak\b/.test(command)) stand.isPlaying = true
    if (/roleplay-stop/.test(command)) stand.isPlaying = false
    if (/roleplay-turn/.test(command) && /--support (hint|shown)/.test(command)) stand.helps += 1
    const stdout = /\bspeak\b/.test(command) ? SPEAK_OUTPUT : '{"status": "stored"}'
    return { result: { stdout, stderr: '', interrupted: false }, text: stdout } as any
  })
  on('model.complete', ($, e) => ({
    value: {
      isAnswered: true,
      text: e.system?.includes('practice tasks') ? CARD.situation : JSON.stringify(verdict),
      usage: { input_tokens: 1, output_tokens: 1, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 },
    },
  }))
  return stand
}
