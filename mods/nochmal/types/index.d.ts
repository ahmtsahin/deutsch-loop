/** A due review, with the new situation the learner is asked about. */
export type NochmalCard = {
  /** Which version of the mod wrote the card. */
  writer: string
  kind: 'pattern' | 'word'
  /** The engine's ID: `m_...` for a pattern, the word's ID for a word. */
  id: string
  /** The pattern's German label, or the word. */
  target: string
  /** A word's meaning cue; null for a pattern. */
  meaning: string | null
  /** A pattern's rule, for the judge; null for a word. */
  rule: string | null
  /** The pattern's first mistake, shown on the card's back after the answer. */
  example: { original: string; corrected: string; seenAtLocal: string | null } | null
  situation: string
  /** Exactly what the engine stores as the review's `--prompt`. */
  prompt: string
  /** ISO code of the learner's explanation language. */
  language: string
}

export type NochmalFeedback = {
  tone: 'pass' | 'fail' | 'info' | 'error'
  text: string
  /** The card's back: the first mistake beside today's sentence; it changes no record. */
  story?: string
}

/** One pattern on the FehlerDNA pane's ladder. */
export type NochmalDnaRow = {
  id: string
  label: string
  status: string
  /** Rungs climbed, 0 to 6 (1, 3, 7, 14, 30, 60 days). */
  step: number
  wrong: number
  right: number
  nextLocal: string | null
  isDue: boolean
}

export type NochmalDna = {
  rows: NochmalDnaRow[]
  mastered: number
  /** The pattern whose journey is open, as the engine's `show --format text` tells it. */
  story: { id: string; label: string; text: string } | null
}

/** The roleplay scene the tutor is running, as the engine records it. */
export type NochmalScene = {
  id: string
  title: string
  role: string | null
  goal: string | null
  personalGoal: string | null
  startedAtMs: number
  targetSeconds: number
  learnerTurns: number
  suggestedTurns: number | null
  /** Partner turns saved with `--support hint` or `shown`. */
  helps: number
  shouldClose: boolean
  isActive: boolean
  /** Frozen length of a scene that has ended. */
  endedSeconds: number | null
  /** The learner pressed Hilfe and the partner's hint is not saved yet. */
  isHelpPending: boolean
}

declare module 'claude-code' {
  interface PluginState {
    nochmal: {
      card: NochmalCard | null
      isShown: boolean
      isJudging: boolean
      feedback: NochmalFeedback | null
      dna: NochmalDna | null
      scene: NochmalScene | null
    }
  }
}
