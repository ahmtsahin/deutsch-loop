import { expect, test } from 'claude-code/testing'

import { COMMAND, PANE, STORY, standIns } from './stand-ins'

const bash = (command: string) => ({ tool: 'Bash' as const, tool_use_id: `toolu_${command.length}`, command })

test('/fehlerdna lists every pattern on its ladder, due ones first', async ($, on) => {
  const stand = standIns(on)
  const opened = await $.command.run({ command: 'fehlerdna', args: '', ...COMMAND })
  expect(opened.text).toBe('FehlerDNA: Panel geöffnet.')
  expect(stand.panes).toContain('fehlerdna')
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'nochmal', surface, ...PANE('fehlerdna') })
    expect(await ui.find({ type: 'Text', text: 'FehlerDNA · 3 Muster · 1 gemeistert' })).toBeDefined()
    const rows = await ui.findAll({ type: 'Button' })
    expect(rows.map(row => row.key)).toEqual(['row:m_wait', 'row:m_later', 'row:m_done'])
    expect(String(rows[0]?.props.label)).toContain('▰▱▱▱▱▱   4× ✗  jetzt fällig')
    expect(String(rows[1]?.props.label)).toContain('▰▰▱▱▱▱   2× ✗  Do 12:00')
    expect(String(rows[2]?.props.label)).toContain('▰▰▰▰▰▰   1× ✗  ★ gemeistert')
    await ui.unmount()
  }
})

test('a ladder row opens the engine’s own story of that pattern, and Zurück returns', async ($, on) => {
  standIns(on)
  await $.command.run({ command: 'fehlerdna', args: '', ...COMMAND })
  const ui = await $.ui.mount({ plugin: 'nochmal', surface: 'desktop', ...PANE('fehlerdna') })
  await ui.press({ key: 'row:m_wait' })
  await ui.unmount()
  const story = await $.ui.mount({ plugin: 'nochmal', surface: 'desktop', ...PANE('fehlerdna') })
  expect(await story.find({ type: 'Text', text: STORY.split('\n')[2] })).toBeDefined()
  await story.press({ key: 'back' })
  await story.unmount()
  const list = await $.ui.mount({ plugin: 'nochmal', surface: 'desktop', ...PANE('fehlerdna') })
  expect(await list.find({ key: 'row:m_wait' })).toBeDefined()
  await list.unmount()
})

test('a scene the tutor starts opens its pane with the role, goal, turns, and time', async ($, on) => {
  const stand = standIns(on)
  await $.tool.call(bash('python scripts/deutsch_loop.py speak restaurant'))
  expect(stand.panes).toContain('szene')
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'nochmal', surface, ...PANE('szene') })
    expect(await ui.find({ type: 'Text', text: 'Partner: a waiter in a busy restaurant' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^Ziel: Handle the reservation/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'Deine Züge: 2 von etwa 8' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^Zeit: 0:30 \/ 5:00 {2}█░{9}$/ })).toBeDefined()
    expect(await ui.find({ key: 'help' })).toBeDefined()
    await ui.unmount()
  }
})

test('the hint that answers Hilfe is saved as support, and the next turn is left alone', async ($, on) => {
  const stand = standIns(on)
  await $.tool.call(bash('python scripts/deutsch_loop.py speak restaurant'))
  const ui = await $.ui.mount({ plugin: 'nochmal', surface: 'desktop', ...PANE('szene') })
  await ui.press({ key: 'help' })
  await ui.unmount()
  expect(stand.prompts).toHaveLength(1)
  expect(stand.prompts[0]).toContain('Hilfe-Knopf')

  await $.tool.call(bash("python scripts/deutsch_loop.py roleplay-turn s_1 --speaker partner --text 'Vielleicht: Ich hätte gern …'"))
  expect(stand.commands.at(-1)).toBe(
    "python scripts/deutsch_loop.py roleplay-turn s_1 --support hint --speaker partner --text 'Vielleicht: Ich hätte gern …'",
  )
  await $.tool.call(bash("python scripts/deutsch_loop.py roleplay-turn s_1 --speaker partner --text 'Sehr gern.'"))
  expect(stand.commands.at(-1)).toBe("python scripts/deutsch_loop.py roleplay-turn s_1 --speaker partner --text 'Sehr gern.'")

  const after = await $.ui.mount({ plugin: 'nochmal', surface: 'desktop', ...PANE('szene') })
  expect(await after.find({ type: 'Text', text: 'Hilfe: 1×' })).toBeDefined()
  await after.unmount()
})

test('a partner turn the tutor marked itself keeps its mark', async ($, on) => {
  const stand = standIns(on)
  await $.tool.call(bash('python scripts/deutsch_loop.py speak restaurant'))
  const ui = await $.ui.mount({ plugin: 'nochmal', surface: 'terminal', ...PANE('szene') })
  await ui.press({ key: 'help' })
  await ui.unmount()
  const shown = "python scripts/deutsch_loop.py roleplay-turn s_1 --speaker partner --support shown --text 'Ich hätte gern einen Tisch.'"
  await $.tool.call(bash(shown))
  expect(stand.commands.at(-1)).toBe(shown)
})

test('an ended scene says so, then its pane closes', async ($, on) => {
  const stand = standIns(on)
  await $.tool.call(bash('python scripts/deutsch_loop.py speak restaurant'))
  await $.tool.call(bash('python scripts/deutsch_loop.py roleplay-stop s_1'))
  const ui = await $.ui.mount({ plugin: 'nochmal', surface: 'desktop', ...PANE('szene') })
  expect(await ui.find({ type: 'Text', text: 'Szene beendet. Das Feedback kommt im Chat.' })).toBeDefined()
  expect(await ui.find({ key: 'help' })).toBeUndefined()
  await ui.unmount()
  await stand.clock.advance(20_000)
  expect(stand.panes).not.toContain('szene')
})

test('commands that are not DeutschLoop’s pass through untouched', async ($, on) => {
  const stand = standIns(on)
  await $.tool.call(bash('git status'))
  expect(stand.commands).toEqual(['git status'])
  expect(stand.runs).toEqual([])
})
