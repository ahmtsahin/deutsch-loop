import { expect, test } from 'claude-code/testing'

import { BAND, CARD, COMMAND, standIns } from './stand-ins'

test('the band stays out of the way without a card', async ($, on) => {
  standIns(on)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'nochmal', surface, ...BAND(true) })
    expect(await ui.find({ key: 'answer' })).toBeUndefined()
    await ui.unmount()
  }
})

test('a shown card draws its situation, an answer field, and a later button', async ($, on) => {
  const stand = standIns(on)
  for (const surface of ['terminal', 'desktop'] as const) {
    stand.state.set('card', { value: CARD, version: 1 })
    stand.state.set('isShown', { value: true, version: 1 })
    const ui = await $.ui.mount({ plugin: 'nochmal', surface, ...BAND(true) })
    expect(await ui.find({ type: 'Text', text: /istasyonda/ })).toBeDefined()
    expect(await ui.find({ key: 'answer' })).toBeDefined()
    await ui.press({ key: 'later' })
    expect(stand.state.get('isShown')?.value).toBe(false)
    await ui.unmount()
  }
})

test('/nochmal opens a due card and a correct answer is graded as a pass', async ($, on) => {
  const stand = standIns(on)
  const opened = await $.command.run({ command: 'nochmal', args: '', ...COMMAND })
  expect(opened.text).toContain('warten auf + Akkusativ')
  expect(stand.state.get('isShown')?.value).toBe(true)
  expect(stand.statuses).toContain('FehlerDNA · fällig: 1 Muster · 17 Tage in Folge')

  const answered = await $.command.run({ command: 'nochmal', args: 'Ich warte am Bahnhof auf dich.', ...COMMAND })
  expect(answered.text).toContain('✓ Richtig.')
  expect(answered.text).toContain('Stufe 1/6 · wieder Do 12:00')
  expect(answered.text).toContain('Am 21.08.: „Ich warte dich.“ · Heute: „Ich warte am Bahnhof auf dich.“ ✓')
  const grade = stand.runs.find(argv => argv.includes('grade'))
  expect(grade?.slice(grade.indexOf('grade'))).toEqual([
    'grade', 'm_wait', '--result', 'pass', '--prompt', CARD.situation, '--answer', 'Ich warte am Bahnhof auf dich.',
  ])
  expect(stand.state.get('card')?.value).toBe(null)
})

test('a wrong answer is graded as a fail with its correction', async ($, on) => {
  const stand = standIns(on, { verdict: 'fail', correction: 'Ich warte auf dich.', note: 'auf eksik.' })
  await $.command.run({ command: 'nochmal', args: '', ...COMMAND })
  const answered = await $.command.run({ command: 'nochmal', args: 'Ich warte dich.', ...COMMAND })
  expect(answered.text).toContain('✗ Ich warte auf dich.')
  expect(answered.text).toContain('Heute: „Ich warte dich.“ ✗')
  const grade = stand.runs.find(argv => argv.includes('grade')) ?? []
  expect(grade.slice(grade.indexOf('--result'), grade.indexOf('--result') + 2)).toEqual(['--result', 'fail'])
  expect(grade.slice(-2)).toEqual(['--correction', 'Ich warte auf dich.'])
})

test('an answer that skips the target keeps the card and grades nothing', async ($, on) => {
  const stand = standIns(on, { verdict: 'missing', correction: '', note: 'warten auf kullanılmadı.' })
  await $.command.run({ command: 'nochmal', args: '', ...COMMAND })
  const answered = await $.command.run({ command: 'nochmal', args: 'Ich bin am Bahnhof.', ...COMMAND })
  expect(answered.text).toContain('Gesucht: warten auf + Akkusativ')
  expect(stand.runs.some(argv => argv.includes('grade'))).toBe(false)
  expect(stand.state.get('card')?.value).toMatchObject({ id: 'm_wait', situation: CARD.situation })
})

test('without a learner folder nothing runs and nothing is created', async ($, on) => {
  const stand = standIns(on, undefined, false)
  const opened = await $.command.run({ command: 'nochmal', args: '', ...COMMAND })
  expect(opened.text).toContain('Noch keine FehlerDNA')
  expect(stand.runs.every(argv => argv.includes('--help'))).toBe(true)
})

test('a card a former version wrote is dropped when the mod loads', async ($, on) => {
  const stand = standIns(on)
  const { writer, ...former } = CARD
  stand.state.set('card', { value: former, version: 1 })
  stand.state.set('isShown', { value: true, version: 1 })
  await $.session.start({ cwd: 'C:/work', surface: 'desktop', isInteractive: true })
  expect(stand.state.get('card')?.value).toBe(null)
  expect(stand.state.get('isShown')?.value).toBe(false)
})

test('the card back shows the first mistake beside today on every surface', async ($, on) => {
  const stand = standIns(on)
  const back = 'Am 21.08.: „Ich warte dich.“ · Heute: „Ich warte am Bahnhof auf dich.“ ✓'
  stand.state.set('feedback', { value: { tone: 'pass', text: '✓ Richtig.', story: back }, version: 1 })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'nochmal', surface, ...BAND(false) })
    expect(await ui.find({ type: 'Text', text: back })).toBeDefined()
    await ui.unmount()
  }
})
