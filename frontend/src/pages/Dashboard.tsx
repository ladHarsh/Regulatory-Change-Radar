// pages/Dashboard.tsx — v3.0: Last-synced timestamp, post-sync doc count polling
import { useState, useEffect, useRef, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import {
  AlertTriangle, TrendingUp, FileText, Clock,
  RefreshCw, Bookmark, ArrowRight, Loader2, ChevronRight, CheckCircle2,
} from 'lucide-react'
import { getStats, getTimeline, triggerIngestion, getDocuments } from '../api/client'
import type { ChangeStats, ChangeRecord } from '../api/client'

// ── Helpers ──────────────────────────────────────────────────────────────────

const SEV_DOT: Record<string, string> = {
  High: 'var(--color-severity-high)',
  Medium: 'var(--color-severity-medium)',
  Low: 'var(--color-severity-low)',
}

const CHANGE_COLORS: Record<string, string> = {
  MODIFIED: 'var(--color-severity-medium)',
  NEW: 'var(--color-severity-low)',
  REMOVED: 'var(--color-severity-high)',
}

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function StatSkeleton() {
  return (
    <div
      className="flex-shrink-0 rounded-2xl p-5 animate-pulse"
      style={{ background: 'var(--color-bg-card)', width: '72vw', maxWidth: 280, border: '1px solid var(--color-border)' }}
    >
      <div className="h-3 w-16 rounded mb-3" style={{ background: 'var(--color-border)' }} />
      <div className="h-8 w-24 rounded" style={{ background: 'var(--color-border)' }} />
    </div>
  )
}

function ChangeSkeleton() {
  return (
    <div className="flex items-center gap-3 py-3 animate-pulse">
      <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: 'var(--color-border)' }} />
      <div className="flex-1">
        <div className="h-3 w-3/4 rounded mb-2" style={{ background: 'var(--color-border)' }} />
        <div className="h-2 w-1/2 rounded" style={{ background: 'var(--color-border)' }} />
      </div>
    </div>
  )
}

// ── Stat Card ─────────────────────────────────────────────────────────────────

interface StatCardProps {
  icon: React.ReactNode
  label: string
  value: string | number
  sub?: string
  accentColor: string
}

function StatCard({ icon, label, value, sub, accentColor }: StatCardProps) {
  return (
    <div
      className="flex-shrink-0 rounded-2xl p-5 relative overflow-hidden"
      style={{
        background: 'var(--color-bg-card)',
        border: '1px solid var(--color-border)',
        width: 'clamp(220px, 72vw, 280px)',
      }}
    >
      <div
        className="absolute top-0 right-0 w-24 h-24 rounded-full opacity-10 -translate-y-8 translate-x-8"
        style={{ background: accentColor }}
      />
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center mb-3"
        style={{ background: `${accentColor}22` }}
      >
        <span style={{ color: accentColor }}>{icon}</span>
      </div>
      <div className="text-3xl font-800 mb-0.5" style={{ color: 'var(--color-text-primary)' }}>
        {value}
      </div>
      <div className="text-xs font-600 uppercase tracking-wide mb-0.5" style={{ color: 'var(--color-text-muted)' }}>
        {label}
      </div>
      {sub && <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{sub}</div>}
    </div>
  )
}

// ── Change List Item ───────────────────────────────────────────────────────────

function ChangeItem({ change, expanded, onToggle }: { change: ChangeRecord; expanded: boolean; onToggle: () => void }) {
  return (
    <div className="border-b" style={{ borderColor: 'var(--color-border)' }}>
      <button
        onClick={onToggle}
        className="w-full text-left py-3 flex items-start gap-3 active:bg-white/5 transition-colors"
      >
        {/* Severity dot */}
        <div
          className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0"
          style={{ background: SEV_DOT[change.severity ?? 'Low'] ?? 'var(--color-text-muted)' }}
        />
        <div className="flex-1 min-w-0">
          {/* Title row */}
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-500 truncate" style={{ color: 'var(--color-text-primary)' }}>
              {change.doc_title ?? 'Regulatory Update'}
            </p>
            <span className="text-[10px] flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
              {relativeTime(change.detected_at)}
            </span>
          </div>
          {/* Badges row */}
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            <span
              className="text-[10px] px-1.5 py-0.5 rounded-md font-600"
              style={{ background: `${SEV_DOT[change.severity ?? 'Low']}22`, color: SEV_DOT[change.severity ?? 'Low'] }}
            >
              {change.severity ?? 'Low'}
            </span>
            <span
              className="text-[10px] px-1.5 py-0.5 rounded-md font-600"
              style={{ background: `${CHANGE_COLORS[change.change_type]}22`, color: CHANGE_COLORS[change.change_type] }}
            >
              {change.change_type}
            </span>
            {change.regulator && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded-md font-500"
                style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-muted)' }}
              >
                {change.regulator}
              </span>
            )}
          </div>
        </div>
        <ChevronRight
          size={14}
          className="flex-shrink-0 mt-1 transition-transform"
          style={{
            color: 'var(--color-text-muted)',
            transform: expanded ? 'rotate(90deg)' : 'none',
          }}
        />
      </button>

      {/* Expandable summary */}
      {expanded && change.impact_summary && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          className="pb-3 pl-5"
        >
          <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
            {change.impact_summary.slice(0, 200)}{change.impact_summary.length > 200 ? '…' : ''}
          </p>
          <Link
            to="/timeline"
            className="text-xs font-500 mt-2 inline-flex items-center gap-1"
            style={{ color: 'var(--color-accent-amber)' }}
          >
            View full diff <ArrowRight size={11} />
          </Link>
        </motion.div>
      )}
    </div>
  )
}

// ── Onboarding Banner ─────────────────────────────────────────────────────────

function OnboardingBanner({ onDismiss }: { onDismiss: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="rounded-2xl p-4 mb-4 flex items-start gap-3"
      style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)' }}
    >
      <span className="text-xl">👋</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-600 mb-0.5" style={{ color: 'var(--color-accent-amber)' }}>
          Welcome to Regulatory Change Radar
        </p>
        <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
          This is sample data. Click <strong>Sync Regulators</strong> to start tracking live RBI &amp; SEBI circulars, or upload a policy document to check for conflicts.
        </p>
      </div>
      <button
        onClick={onDismiss}
        className="text-xs px-2 py-1 rounded-lg flex-shrink-0 active:scale-95 transition-transform"
        style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-muted)' }}
      >
        Dismiss
      </button>
    </motion.div>
  )
}

// ── Main Dashboard ─────────────────────────────────────────────────────────────

export function Dashboard() {
  const [stats, setStats] = useState<ChangeStats | null>(null)
  const [changes, setChanges] = useState<ChangeRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [syncStatus, setSyncStatus] = useState<'idle' | 'syncing' | 'done' | 'error'>('idle')
  const [syncMsg, setSyncMsg] = useState('')
  const [lastSynced, setLastSynced] = useState<string | null>(
    () => localStorage.getItem('radar-last-synced')
  )
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [showBanner, setShowBanner] = useState(false)
  const [activeCardIndex, setActiveCardIndex] = useState(0)
  const carouselRef = useRef<HTMLDivElement>(null)
  const syncPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, c] = await Promise.all([getStats(), getTimeline({ limit: 20 })])
      setStats(s)
      setChanges(c)
      if (c.length === 0) {
        const dismissed = localStorage.getItem('onboarding-dismissed')
        if (!dismissed) setShowBanner(true)
      }
    } catch {
      // silently fail — shows empty state
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // After triggering sync, poll doc count to detect when ingestion actually produces results
  const startSyncPolling = useCallback((prevDocCount: number) => {
    if (syncPollRef.current) clearInterval(syncPollRef.current)
    let attempts = 0
    syncPollRef.current = setInterval(async () => {
      attempts++
      if (attempts > 30) { // 30 * 3s = 90s max
        clearInterval(syncPollRef.current!)
        syncPollRef.current = null
        setSyncStatus('error')
        setSyncMsg('Sync timed out — check backend logs.')
        return
      }
      try {
        const docs = await getDocuments()
        if (docs.length > prevDocCount) {
          clearInterval(syncPollRef.current!)
          syncPollRef.current = null
          const now = new Date().toISOString()
          localStorage.setItem('radar-last-synced', now)
          setLastSynced(now)
          setSyncStatus('done')
          setSyncMsg(`✓ Synced ${docs.length - prevDocCount} new document${docs.length - prevDocCount !== 1 ? 's' : ''}`)
          load() // Refresh stats + timeline
        }
      } catch { /* ignore poll errors */ }
    }, 3000)
  }, [load])

  // Cleanup poll on unmount
  useEffect(() => () => { if (syncPollRef.current) clearInterval(syncPollRef.current) }, [])

  // Sync scroll position with active card indicator
  useEffect(() => {
    const el = carouselRef.current
    if (!el) return
    const handleScroll = () => {
      if (!el.children.length) return
      const childWidth = (el.children[0] as HTMLElement).offsetWidth || 250
      const gap = 12 // 0.75rem (gap-3)
      const newIndex = Math.round(el.scrollLeft / (childWidth + gap))
      setActiveCardIndex(Math.min((stats ? 4 : 0) - 1, Math.max(0, newIndex)))
    }
    el.addEventListener('scroll', handleScroll, { passive: true })
    return () => el.removeEventListener('scroll', handleScroll)
  }, [stats])

  const scrollToCard = (index: number) => {
    const el = carouselRef.current
    if (!el || !el.children.length) return
    const childWidth = (el.children[0] as HTMLElement).offsetWidth || 250
    const gap = 12
    el.scrollTo({ left: index * (childWidth + gap), behavior: 'smooth' })
  }

  const handleSync = async () => {
    setSyncing(true)
    setSyncStatus('syncing')
    setSyncMsg('Syncing regulators…')
    try {
      const prevDocs = await getDocuments()
      await triggerIngestion()
      setSyncing(false)
      setSyncMsg('Ingestion started — watching for new documents…')
      startSyncPolling(prevDocs.length)
    } catch {
      setSyncStatus('error')
      setSyncMsg('Failed — backend unreachable.')
      setSyncing(false)
    }
  }

  // Build stat cards array
  const statCards = stats ? [
    { icon: <AlertTriangle size={18} />, label: 'High Severity', value: stats.high_severity_count, accentColor: '#ef4444' },
    { icon: <TrendingUp size={18} />, label: 'This Month', value: stats.changes_this_month, accentColor: '#f59e0b' },
    { icon: <FileText size={18} />, label: 'Total Changes', value: stats.total_changes, accentColor: '#6366f1' },
    { icon: <Clock size={18} />, label: 'Low Severity', value: stats.low_severity_count, accentColor: '#10b981' },
  ] : []

  return (
    <div className="p-4 lg:p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div className="hidden lg:block">
          <h1 className="text-2xl font-800" style={{ color: 'var(--color-text-primary)' }}>
            Compliance Dashboard
          </h1>
          <p className="text-sm mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
            Tracking RBI · SEBI · IRDAI
          </p>
        </div>
        <div className="flex items-center gap-2 ml-auto">
          {/* Sync status + last synced */}
          <div className="flex flex-col items-end gap-0.5">
            {syncMsg && (
              <span
                className="text-xs px-2 py-1 rounded-lg flex items-center gap-1"
                style={{
                  background: syncStatus === 'done' ? 'rgba(16,185,129,0.1)' : syncStatus === 'error' ? 'rgba(239,68,68,0.1)' : 'var(--color-bg-card)',
                  color: syncStatus === 'done' ? 'var(--color-severity-low)' : syncStatus === 'error' ? 'var(--color-severity-high)' : 'var(--color-text-secondary)',
                  border: `1px solid ${syncStatus === 'done' ? 'rgba(16,185,129,0.2)' : syncStatus === 'error' ? 'rgba(239,68,68,0.2)' : 'var(--color-border)'}`,
                }}
              >
                {syncStatus === 'done' && <CheckCircle2 size={11} />}
                {syncStatus === 'error' && <AlertTriangle size={11} />}
                {syncStatus === 'syncing' && <Loader2 size={11} className="animate-spin" />}
                {syncMsg}
              </span>
            )}
            {lastSynced && !syncMsg && (
              <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                Last synced {new Date(lastSynced).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="btn-primary flex items-center gap-2 text-sm px-4 py-2 rounded-xl active:scale-95 transition-transform disabled:opacity-60"
            id="sync-regulators-btn"
          >
            {syncing ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            <span className="hidden sm:inline">{syncing ? 'Syncing…' : 'Sync Regulators'}</span>
            <span className="sm:hidden">{syncing ? '…' : 'Sync'}</span>
          </button>
        </div>
      </div>

      {/* Onboarding banner */}
      {showBanner && <OnboardingBanner onDismiss={() => { setShowBanner(false); localStorage.setItem('onboarding-dismissed', '1') }} />}

      {/* ── STAT CARDS ────────────────────────────────────────────────────── */}
      {/* Mobile: horizontal swipeable carousel */}
      <div className="lg:hidden mb-6">
        <div
          ref={carouselRef}
          className="flex gap-3 overflow-x-auto pb-3 snap-x snap-mandatory no-scrollbar"
          style={{ scrollbarWidth: 'none', WebkitOverflowScrolling: 'touch' }}
        >
          {loading
            ? [0, 1, 2, 3].map(i => (
                <div key={i} className="snap-start flex-shrink-0">
                  <StatSkeleton />
                </div>
              ))
            : statCards.map((card, i) => (
                <div key={i} className="snap-start flex-shrink-0">
                  <StatCard {...card} sub={undefined} />
                </div>
              ))
          }
          {/* Trailing spacer so last card isn't flush with edge */}
          <div className="flex-shrink-0 w-4" />
        </div>
        {/* Scroll hint dots */}
        <div className="flex justify-center gap-1.5 mt-1">
          {statCards.map((_, i) => (
            <button
              key={i}
              onClick={() => scrollToCard(i)}
              className="w-2 h-2 rounded-full transition-all duration-300"
              style={{ background: i === activeCardIndex ? 'var(--color-accent-amber)' : 'var(--color-border)' }}
              aria-label={`Scroll to card ${i + 1}`}
            />
          ))}
        </div>
      </div>

      {/* Desktop: 4-column grid */}
      <div className="hidden lg:grid grid-cols-4 gap-4 mb-8">
        {loading
          ? [0, 1, 2, 3].map(i => <StatSkeleton key={i} />)
          : statCards.map((card, i) => <StatCard key={i} {...card} />)
        }
      </div>

      {/* ── RECENT CHANGES ────────────────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-700" style={{ color: 'var(--color-text-primary)' }}>
            Recent Changes
          </h2>
          <Link
            to="/timeline"
            className="text-xs flex items-center gap-1 font-500"
            style={{ color: 'var(--color-accent-amber)' }}
            id="view-all-changes-link"
          >
            View all <ArrowRight size={12} />
          </Link>
        </div>

        {/* Mobile: dense list */}
        <div className="lg:hidden">
          {loading
            ? [0, 1, 2, 3, 4].map(i => (
                <div key={i} className="border-b py-3" style={{ borderColor: 'var(--color-border)' }}>
                  <ChangeSkeleton />
                </div>
              ))
            : changes.length === 0
              ? (
                <div className="py-12 text-center">
                  <Bookmark size={32} className="mx-auto mb-3 opacity-30" />
                  <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                    No changes yet — click Sync to start
                  </p>
                </div>
              )
              : changes.map(c => (
                <ChangeItem
                  key={c.id}
                  change={c}
                  expanded={expandedId === c.id}
                  onToggle={() => setExpandedId(expandedId === c.id ? null : c.id)}
                />
              ))
          }
        </div>

        {/* Desktop: card grid */}
        <div className="hidden lg:grid grid-cols-1 gap-3">
          {loading
            ? [0, 1, 2].map(i => (
                <div key={i} className="card p-5 animate-pulse">
                  <div className="h-4 w-3/4 rounded mb-2" style={{ background: 'var(--color-border)' }} />
                  <div className="h-3 w-full rounded mb-1" style={{ background: 'var(--color-border)' }} />
                  <div className="h-3 w-2/3 rounded" style={{ background: 'var(--color-border)' }} />
                </div>
              ))
            : changes.length === 0
              ? (
                <div className="card p-12 text-center">
                  <Bookmark size={40} className="mx-auto mb-4 opacity-30" />
                  <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                    No changes detected yet. Click <strong>Sync Regulators</strong> to start tracking.
                  </p>
                </div>
              )
              : changes.map(c => (
                <div key={c.id} className="card p-5 hover:border-amber-500/30 transition-colors">
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <h3 className="font-600 text-sm" style={{ color: 'var(--color-text-primary)' }}>
                      {c.doc_title ?? 'Regulatory Update'}
                    </h3>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span
                        className="text-[10px] px-2 py-0.5 rounded-full font-600"
                        style={{ background: `${SEV_DOT[c.severity ?? 'Low']}22`, color: SEV_DOT[c.severity ?? 'Low'] }}
                      >
                        {c.severity ?? 'Low'}
                      </span>
                      <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                        {relativeTime(c.detected_at)}
                      </span>
                    </div>
                  </div>
                  {c.impact_summary && (
                    <p className="text-xs leading-relaxed line-clamp-2" style={{ color: 'var(--color-text-secondary)' }}>
                      {c.impact_summary}
                    </p>
                  )}
                  <div className="flex items-center gap-2 mt-3">
                    {c.regulator && (
                      <span
                        className="text-[10px] px-2 py-0.5 rounded-full font-500"
                        style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-muted)' }}
                      >
                        {c.regulator}
                      </span>
                    )}
                    <span
                      className="text-[10px] px-2 py-0.5 rounded-full font-600"
                      style={{ background: `${CHANGE_COLORS[c.change_type]}22`, color: CHANGE_COLORS[c.change_type] }}
                    >
                      {c.change_type}
                    </span>
                  </div>
                </div>
              ))
          }
        </div>
      </div>
    </div>
  )
}
