// pages/Timeline.tsx — v3.0: Persistent filters via Zustand, fixed regulator filter
import { useState, useEffect, useCallback, useMemo } from 'react'

import { GitCompare, Filter, Loader2, AlertTriangle, ChevronRight, RefreshCw } from 'lucide-react'
import { getTimeline } from '../api/client'
import type { ChangeRecord } from '../api/client'
import { BottomSheet } from '../components/BottomSheet'
import { DiffToggle } from '../components/DiffView'
import { useFiltersStore } from '../store'

// ── Constants ────────────────────────────────────────────────────────────────

const SEV_COLOR: Record<string, string> = {
  High: 'var(--color-severity-high)',
  Medium: 'var(--color-severity-medium)',
  Low: 'var(--color-severity-low)',
}

const CHANGE_COLOR: Record<string, string> = {
  MODIFIED: 'var(--color-severity-medium)',
  NEW: 'var(--color-severity-low)',
  REMOVED: 'var(--color-severity-high)',
}

const SEVERITY_FILTERS = ['All', 'High', 'Medium', 'Low']
const TYPE_FILTERS = ['All', 'MODIFIED', 'NEW', 'REMOVED']
const REGULATOR_FILTERS = ['All', 'RBI', 'SEBI', 'IRDAI']

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

function groupByDay(changes: ChangeRecord[]): [string, ChangeRecord[]][] {
  const map = new Map<string, ChangeRecord[]>()
  for (const c of changes) {
    const day = formatDate(c.detected_at)
    if (!map.has(day)) map.set(day, [])
    map.get(day)!.push(c)
  }
  return Array.from(map.entries())
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function TimelineSkeleton() {
  return (
    <div className="space-y-3">
      {[0, 1, 2, 3].map(i => (
        <div key={i} className="card p-4 animate-pulse">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-2 h-2 rounded-full" style={{ background: 'var(--color-border)' }} />
            <div className="h-3 w-2/3 rounded" style={{ background: 'var(--color-border)' }} />
          </div>
          <div className="h-2 w-full rounded mb-1" style={{ background: 'var(--color-border)' }} />
          <div className="h-2 w-3/4 rounded" style={{ background: 'var(--color-border)' }} />
        </div>
      ))}
    </div>
  )
}

// ── Filter Chip Bar ────────────────────────────────────────────────────────────

interface ChipBarProps {
  label: string
  options: string[]
  value: string
  onChange: (v: string) => void
}

function ChipBar({ label, options, value, onChange }: ChipBarProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-600 flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
        {label}
      </span>
      <div
        className="flex gap-1.5 overflow-x-auto pb-0.5 no-scrollbar"
        style={{ scrollbarWidth: 'none' }}
      >
        {options.map(opt => (
          <button
            key={opt}
            onClick={() => onChange(opt)}
            className="flex-shrink-0 text-xs px-3 py-1 rounded-full font-500 transition-all duration-150 active:scale-95"
            style={{
              background: value === opt ? 'var(--color-accent-amber)' : 'var(--color-bg-secondary)',
              color: value === opt ? '#1a0a00' : 'var(--color-text-secondary)',
              border: `1px solid ${value === opt ? 'var(--color-accent-amber)' : 'var(--color-border)'}`,
            }}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Change Card ────────────────────────────────────────────────────────────────

interface ChangeCardProps {
  change: ChangeRecord
  onTap: () => void
}

function ChangeCard({ change, onTap }: ChangeCardProps) {
  return (
    <button
      onClick={onTap}
      className="w-full text-left card p-4 hover:border-amber-500/30 active:scale-[0.99] transition-all duration-150 flex items-start gap-3"
      id={`change-card-${change.id}`}
    >
      {/* Timeline dot */}
      <div
        className="w-2.5 h-2.5 rounded-full flex-shrink-0 mt-1"
        style={{ background: SEV_COLOR[change.severity ?? 'Low'] }}
      />

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2 mb-1">
          <p className="text-sm font-600 truncate" style={{ color: 'var(--color-text-primary)' }}>
            {change.doc_title ?? 'Regulatory Update'}
          </p>
          <ChevronRight size={14} className="flex-shrink-0 mt-0.5" style={{ color: 'var(--color-text-muted)' }} />
        </div>

        {change.new_section_ref && (
          <p className="text-xs mb-1.5 truncate" style={{ color: 'var(--color-text-muted)' }}>
            § {change.new_section_ref}
          </p>
        )}

        {/* Impact summary (first 100 chars) */}
        {change.impact_summary && (
          <p className="text-xs leading-relaxed line-clamp-2 mb-2" style={{ color: 'var(--color-text-secondary)' }}>
            {change.impact_summary}
          </p>
        )}

        <div className="flex items-center gap-1.5 flex-wrap">
          <span
            className="text-[10px] px-2 py-0.5 rounded-full font-600"
            style={{ background: `${SEV_COLOR[change.severity ?? 'Low']}22`, color: SEV_COLOR[change.severity ?? 'Low'] }}
          >
            {change.severity ?? 'Low'}
          </span>
          <span
            className="text-[10px] px-2 py-0.5 rounded-full font-600"
            style={{ background: `${CHANGE_COLOR[change.change_type]}22`, color: CHANGE_COLOR[change.change_type] }}
          >
            {change.change_type}
          </span>
          {change.regulator && (
            <span
              className="text-[10px] px-2 py-0.5 rounded-full font-500"
              style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-muted)' }}
            >
              {change.regulator}
            </span>
          )}
          {change.affected_area && (
            <span
              className="text-[10px] px-2 py-0.5 rounded-full font-500"
              style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-muted)' }}
            >
              {change.affected_area}
            </span>
          )}
        </div>
      </div>
    </button>
  )
}

// ── Change Detail Bottom Sheet ────────────────────────────────────────────────

function ChangeDetail({ change }: { change: ChangeRecord }) {
  return (
    <div className="space-y-5">
      {/* Meta */}
      <div className="flex flex-wrap gap-2">
        <span
          className="text-xs px-2.5 py-1 rounded-full font-600"
          style={{ background: `${SEV_COLOR[change.severity ?? 'Low']}22`, color: SEV_COLOR[change.severity ?? 'Low'] }}
        >
          {change.severity ?? 'Low'} Severity
        </span>
        <span
          className="text-xs px-2.5 py-1 rounded-full font-600"
          style={{ background: `${CHANGE_COLOR[change.change_type]}22`, color: CHANGE_COLOR[change.change_type] }}
        >
          {change.change_type}
        </span>
        {change.regulator && (
          <span
            className="text-xs px-2.5 py-1 rounded-full font-500"
            style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
          >
            {change.regulator}
          </span>
        )}
        {change.risk_direction && (
          <span
            className="text-xs px-2.5 py-1 rounded-full font-500"
            style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
          >
            Risk {change.risk_direction}
          </span>
        )}
      </div>

      {/* AI Impact Summary */}
      {change.impact_summary && (
        <div>
          <p className="text-xs font-700 uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-muted)' }}>
            AI Impact Summary
          </p>
          <div
            className="rounded-xl p-4 text-sm leading-relaxed"
            style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
          >
            {change.impact_summary}
          </div>
        </div>
      )}

      {/* Word-level diff */}
      <div>
        <p className="text-xs font-700 uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-muted)' }}>
          Clause Diff
        </p>
        <DiffToggle
          oldText={change.old_clause ?? null}
          newText={change.new_clause ?? null}
          showDiff
        />
      </div>

      {/* Affected area */}
      {change.affected_area && (
        <div>
          <p className="text-xs font-700 uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-muted)' }}>
            Affected Business Area
          </p>
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{change.affected_area}</p>
        </div>
      )}

      {/* Similarity score */}
      {change.similarity_score != null && (
        <div>
          <p className="text-xs font-700 uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-muted)' }}>
            Semantic Similarity Score
          </p>
          <div className="flex items-center gap-3">
            <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-bg-secondary)' }}>
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.round(change.similarity_score * 100)}%`,
                  background: 'var(--color-accent-amber)',
                }}
              />
            </div>
            <span className="text-sm font-600" style={{ color: 'var(--color-text-primary)' }}>
              {(change.similarity_score * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Timeline Page ─────────────────────────────────────────────────────────

export function Timeline() {
  const [changes, setChanges] = useState<ChangeRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<ChangeRecord | null>(null)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [hasEverLoaded, setHasEverLoaded] = useState(false)

  // Persistent filter state — survives tab switches
  const {
    timelineSeverity: severity,
    timelineChangeType: changeType,
    timelineRegulator: regulator,
    setTimelineSeverity: setSeverity,
    setTimelineChangeType: setChangeType,
    setTimelineRegulator: setRegulator,
  } = useFiltersStore()

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getTimeline({
        severity: severity === 'All' ? undefined : severity,
        change_type: changeType === 'All' ? undefined : changeType,
        regulator: regulator === 'All' ? undefined : regulator,
        limit: 100,
      })
      setChanges(data)
      setHasEverLoaded(true)
    } catch {
      setError('Failed to load — is the backend running?')
    } finally {
      setLoading(false)
    }
  }, [severity, changeType, regulator])

  useEffect(() => { load() }, [load])

  const groups = useMemo(() => groupByDay(changes), [changes])

  return (
    <div className="max-w-3xl mx-auto">
      {/* ── Desktop header ──────────────────────────────────────── */}
      <div className="hidden lg:flex items-center justify-between p-6 pb-0">
        <div>
          <h1 className="text-2xl font-800" style={{ color: 'var(--color-text-primary)' }}>
            Change Timeline
          </h1>
          <p className="text-sm mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
            {changes.length} changes detected
          </p>
        </div>
      </div>

      {/* ── Filter chips — scrollable row ───────────────────────── */}
      <div
        className="sticky top-0 z-10 px-4 py-3 border-b space-y-2"
        style={{
          background: 'var(--color-bg-primary)',
          borderColor: 'var(--color-border)',
          backdropFilter: 'blur(10px)',
        }}
      >
        <div className="flex items-center gap-2">
          <button
            onClick={() => setFiltersOpen(!filtersOpen)}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border active:scale-95 transition-transform flex-shrink-0"
            style={{
              borderColor: filtersOpen ? 'var(--color-accent-amber)' : 'var(--color-border)',
              color: filtersOpen ? 'var(--color-accent-amber)' : 'var(--color-text-secondary)',
              background: filtersOpen ? 'var(--color-accent-amber-dim)' : 'transparent',
            }}
          >
            <Filter size={12} />
            Filters
          </button>
          {/* Quick severity chips */}
          <div className="flex gap-1.5 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
            {SEVERITY_FILTERS.map(s => (
              <button
                key={s}
                onClick={() => setSeverity(s)}
                className="flex-shrink-0 text-xs px-3 py-1 rounded-full font-500 transition-all duration-150 active:scale-95"
                style={{
                  background: severity === s ? 'var(--color-accent-amber)' : 'var(--color-bg-secondary)',
                  color: severity === s ? '#1a0a00' : 'var(--color-text-secondary)',
                  border: `1px solid ${severity === s ? 'var(--color-accent-amber)' : 'var(--color-border)'}`,
                }}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* Expanded filters */}
        {filtersOpen && (
          <div className="space-y-2 pt-1">
            <ChipBar label="Type" options={TYPE_FILTERS} value={changeType} onChange={setChangeType} />
            <ChipBar label="Source" options={REGULATOR_FILTERS} value={regulator} onChange={setRegulator} />
          </div>
        )}
      </div>

      {/* ── Content ─────────────────────────────────────────────── */}
      <div className="px-4 py-4 lg:px-6 lg:py-5 space-y-6">
        {error && (
          <div className="card p-4 flex items-center gap-3">
            <AlertTriangle size={18} style={{ color: 'var(--color-severity-high)' }} />
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{error}</p>
          </div>
        )}

        {loading
          ? <TimelineSkeleton />
          : error
            ? null  // error banner already shown above
            : changes.length === 0
              ? (
                <div className="text-center py-16">
                  <GitCompare size={40} className="mx-auto mb-4 opacity-30" />
                  {!hasEverLoaded || (severity === 'All' && changeType === 'All' && regulator === 'All')
                    ? (
                      <>
                        <p className="font-600 mb-2" style={{ color: 'var(--color-text-primary)' }}>No changes detected yet</p>
                        <p className="text-sm mb-4" style={{ color: 'var(--color-text-muted)' }}>
                          Run a sync on the Dashboard to start tracking regulatory changes
                        </p>
                        <a
                          href="/"
                          className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-xl font-600 active:scale-95 transition-transform"
                          style={{ background: 'var(--color-accent-amber)', color: '#1a0a00' }}
                        >
                          <RefreshCw size={14} /> Go to Dashboard
                        </a>
                      </>
                    )
                    : (
                      <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                        No changes match this filter — try adjusting your criteria
                      </p>
                    )
                  }
                </div>
              )
              : groups.map(([day, dayChanges]) => (
              <div key={day}>
                {/* Sticky day header */}
                <div
                  className="sticky z-10 py-1.5 mb-3"
                  style={{ top: filtersOpen ? 130 : 57, background: 'var(--color-bg-primary)' }}
                >
                  <span
                    className="text-xs font-700 uppercase tracking-wider px-2 py-0.5 rounded-md"
                    style={{ background: 'var(--color-bg-card)', color: 'var(--color-text-muted)', border: '1px solid var(--color-border)' }}
                  >
                    {day}
                  </span>
                </div>

                {/* Change cards for this day */}
                <div className="space-y-2.5 pl-0 lg:pl-4 border-l-0 lg:border-l" style={{ borderColor: 'var(--color-border)' }}>
                  {dayChanges.map(c => (
                    <ChangeCard key={c.id} change={c} onTap={() => setSelected(c)} />
                  ))}
                </div>
              </div>
            ))
        }

        {loading && (
          <div className="flex justify-center py-4">
            <Loader2 size={20} className="animate-spin" style={{ color: 'var(--color-accent-amber)' }} />
          </div>
        )}
      </div>

      {/* ── Change Detail Bottom Sheet ──────────────────────────── */}
      <BottomSheet
        isOpen={selected !== null}
        onClose={() => setSelected(null)}
        title={selected?.doc_title ?? 'Change Detail'}
        snapHeight={85}
      >
        {selected && <ChangeDetail change={selected} />}
      </BottomSheet>
    </div>
  )
}
