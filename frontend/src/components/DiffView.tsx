// components/DiffView.tsx — Word-level diff highlighting using diff-match-patch
// Used in Timeline (modified clauses) and PolicyCheck (conflict comparison)
import { useMemo } from 'react'
import { diff_match_patch, DIFF_INSERT, DIFF_DELETE, DIFF_EQUAL } from 'diff-match-patch'

interface DiffViewProps {
  oldText: string
  newText: string
}

export function DiffView({ oldText, newText }: DiffViewProps) {
  const diffs = useMemo(() => {
    const dmp = new diff_match_patch()

    // Word-level diff: split on word/non-word token boundaries, assign unique character code to each token
    const tokenize = (text: string): string[] => {
      return text.match(/[a-zA-Z0-9]+|[^a-zA-Z0-9]+/g) || []
    }

    const diff_wordsToChars = (t1: string, t2: string) => {
      const lineArray: string[] = ['']
      const lineHash: Record<string, number> = {}

      const munge = (text: string): string => {
        const tokens = tokenize(text)
        let chars = ''
        for (const token of tokens) {
          if (Object.prototype.hasOwnProperty.call(lineHash, token)) {
            chars += String.fromCharCode(lineHash[token])
          } else {
            lineArray.push(token)
            lineHash[token] = lineArray.length - 1
            chars += String.fromCharCode(lineArray.length - 1)
          }
        }
        return chars
      }

      const chars1 = munge(t1)
      const chars2 = munge(t2)
      return { chars1, chars2, lineArray }
    }

    const { chars1, chars2, lineArray } = diff_wordsToChars(oldText, newText)
    const d = dmp.diff_main(chars1, chars2)
    dmp.diff_charsToLines_(d, lineArray)
    dmp.diff_cleanupSemantic(d)
    return d
  }, [oldText, newText])

  return (
    <div
      className="rounded-lg p-4 text-sm leading-relaxed"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
        fontFamily: 'monospace',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}
    >
      {diffs.map((diff, i) => {
        const [op, text] = diff
        if (op === DIFF_EQUAL) {
          return (
            <span key={i} style={{ color: 'var(--color-text-secondary)' }}>
              {text}
            </span>
          )
        }
        if (op === DIFF_DELETE) {
          return (
            <span
              key={i}
              style={{
                background: 'rgba(239,68,68,0.15)',
                color: '#fca5a5',
                textDecoration: 'line-through',
                borderRadius: 3,
                padding: '0 2px',
              }}
            >
              {text}
            </span>
          )
        }
        if (op === DIFF_INSERT) {
          return (
            <span
              key={i}
              style={{
                background: 'rgba(16,185,129,0.15)',
                color: '#6ee7b7',
                borderRadius: 3,
                padding: '0 2px',
              }}
            >
              {text}
            </span>
          )
        }
        return null
      })}
    </div>
  )
}

// ── Before/After Toggle ───────────────────────────────────────────────────────

interface DiffToggleProps {
  oldText: string | null
  newText: string | null
  /** When true, uses word-level diff on the unified view */
  showDiff?: boolean
}

export function DiffToggle({ oldText, newText, showDiff = true }: DiffToggleProps) {
  if (!oldText && !newText) return null

  // New clause only
  if (!oldText) {
    return (
      <div>
        <p className="text-xs font-600 mb-2 uppercase tracking-wide" style={{ color: 'var(--color-severity-low)' }}>
          New Clause
        </p>
        <div
          className="rounded-lg p-4 text-sm leading-relaxed"
          style={{
            background: 'rgba(16,185,129,0.06)',
            border: '1px solid rgba(16,185,129,0.2)',
            color: 'var(--color-text-secondary)',
            fontFamily: 'monospace',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {newText}
        </div>
      </div>
    )
  }

  // Removed clause only
  if (!newText) {
    return (
      <div>
        <p className="text-xs font-600 mb-2 uppercase tracking-wide" style={{ color: 'var(--color-severity-high)' }}>
          Removed Clause
        </p>
        <div
          className="rounded-lg p-4 text-sm leading-relaxed"
          style={{
            background: 'rgba(239,68,68,0.06)',
            border: '1px solid rgba(239,68,68,0.2)',
            color: '#fca5a5',
            fontFamily: 'monospace',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            textDecoration: 'line-through',
          }}
        >
          {oldText}
        </div>
      </div>
    )
  }

  // Modified — show word-level diff
  if (showDiff) {
    return (
      <div>
        <p className="text-xs font-600 mb-2 uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
          Word-Level Diff
        </p>
        <DiffView oldText={oldText} newText={newText} />
        <p className="text-xs mt-2" style={{ color: 'var(--color-text-muted)' }}>
          <span style={{ background: 'rgba(239,68,68,0.15)', color: '#fca5a5', padding: '0 4px', borderRadius: 3 }}>Removed</span>
          {' '}·{' '}
          <span style={{ background: 'rgba(16,185,129,0.15)', color: '#6ee7b7', padding: '0 4px', borderRadius: 3 }}>Added</span>
        </p>
      </div>
    )
  }

  return null
}
