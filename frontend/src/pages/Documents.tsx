// pages/Documents.tsx — v3.0: Persistent filters via Zustand, real version history
import { useState, useEffect, useCallback } from 'react'
import { Library, RefreshCw, GitBranch, ExternalLink, ChevronRight, AlertTriangle, Loader2 } from 'lucide-react'
import { getDocuments, getDocumentVersions } from '../api/client'
import type { DocumentItem, DocumentVersionOut } from '../api/client'
import { BottomSheet } from '../components/BottomSheet'
import { useFiltersStore } from '../store'

// ── Helpers ───────────────────────────────────────────────────────────────────

const REG_COLORS: Record<string, string> = {
  RBI: '#3b82f6',
  SEBI: '#6366f1',
  IRDAI: '#10b981',
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function DocSkeleton() {
  return (
    <div className="card p-4 animate-pulse">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl flex-shrink-0" style={{ background: 'var(--color-border)' }} />
        <div className="flex-1">
          <div className="h-3 w-3/4 rounded mb-2" style={{ background: 'var(--color-border)' }} />
          <div className="h-2 w-1/2 rounded" style={{ background: 'var(--color-border)' }} />
        </div>
      </div>
    </div>
  )
}

// ── Filter Chips ──────────────────────────────────────────────────────────────

const SOURCE_FILTERS = ['All', 'RBI', 'SEBI', 'IRDAI']
const SORT_OPTIONS = ['Newest', 'Oldest', 'Most Versions']

interface FilterBarProps {
  source: string
  setSource: (s: string) => void
  sort: string
  setSort: (s: string) => void
}

function FilterBar({ source, setSource, sort, setSort }: FilterBarProps) {
  return (
    <div
      className="sticky top-0 z-10 px-4 py-3 border-b space-y-2"
      style={{
        background: 'var(--color-bg-primary)',
        borderColor: 'var(--color-border)',
        backdropFilter: 'blur(10px)',
      }}
    >
      {/* Source filter */}
      <div className="flex gap-1.5 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
        {SOURCE_FILTERS.map(s => (
          <button
            key={s}
            onClick={() => setSource(s)}
            className="flex-shrink-0 text-xs px-3 py-1.5 rounded-full font-500 transition-all duration-150 active:scale-95"
            style={{
              background: source === s ? (REG_COLORS[s] ?? 'var(--color-accent-amber)') : 'var(--color-bg-secondary)',
              color: source === s ? 'white' : 'var(--color-text-secondary)',
              border: `1px solid ${source === s ? 'transparent' : 'var(--color-border)'}`,
            }}
          >
            {s}
          </button>
        ))}
        <div className="w-px h-6 self-center flex-shrink-0" style={{ background: 'var(--color-border)' }} />
        {/* Sort */}
        {SORT_OPTIONS.map(s => (
          <button
            key={s}
            onClick={() => setSort(s)}
            className="flex-shrink-0 text-xs px-3 py-1.5 rounded-full font-500 transition-all duration-150 active:scale-95"
            style={{
              background: sort === s ? 'var(--color-accent-amber)' : 'transparent',
              color: sort === s ? '#1a0a00' : 'var(--color-text-muted)',
              border: `1px solid ${sort === s ? 'var(--color-accent-amber)' : 'transparent'}`,
            }}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Document Card ─────────────────────────────────────────────────────────────

interface DocCardProps {
  doc: DocumentItem
  onTap: () => void
}

function DocCard({ doc, onTap }: DocCardProps) {
  const color = REG_COLORS[doc.regulator] ?? '#6b7280'

  return (
    <button
      onClick={onTap}
      className="w-full text-left card p-4 active:scale-[0.99] transition-all duration-150 hover:border-amber-500/30 flex items-start gap-3"
      id={`doc-card-${doc.id}`}
    >
      {/* Regulator badge icon */}
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 text-white text-xs font-800"
        style={{ background: color }}
      >
        {doc.regulator?.slice(0, 1) ?? 'R'}
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-600 leading-tight line-clamp-2 text-left mb-1.5" style={{ color: 'var(--color-text-primary)' }}>
          {doc.title || doc.url || 'Untitled Document'}
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="text-[10px] px-2 py-0.5 rounded-full font-700"
            style={{ background: `${color}22`, color }}
          >
            {doc.regulator}
          </span>
          <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
            v{doc.version_count ?? 1}
          </span>
          <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
            {formatDate(doc.created_at)}
          </span>
        </div>
      </div>

      <ChevronRight size={14} className="flex-shrink-0 mt-1" style={{ color: 'var(--color-text-muted)' }} />
    </button>
  )
}

// ── Document Detail Bottom Sheet ──────────────────────────────────────────────

function DocDetail({ doc }: { doc: DocumentItem }) {
  const color = REG_COLORS[doc.regulator] ?? '#6b7280'
  const [versions, setVersions] = useState<DocumentVersionOut[]>([])
  const [loadingVersions, setLoadingVersions] = useState(false)

  // Fetch real version history when the sheet opens
  useEffect(() => {
    if (!doc.id) return
    setLoadingVersions(true)
    getDocumentVersions(doc.id)
      .then(setVersions)
      .catch(() => setVersions([]))
      .finally(() => setLoadingVersions(false))
  }, [doc.id])

  return (
    <div className="space-y-5">
      {/* Meta */}
      <div className="flex items-start gap-3">
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center text-white font-800 text-sm flex-shrink-0"
          style={{ background: color }}
        >
          {doc.regulator?.slice(0, 1) ?? 'R'}
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-600 leading-snug" style={{ color: 'var(--color-text-primary)' }}>{doc.title || doc.url || 'Untitled Document'}</p>
          <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
            {doc.regulator} · {doc.doc_type ?? 'circular'}
          </p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Versions', value: doc.version_count ?? 1 },
          { label: 'Added', value: formatDate(doc.created_at) },
          { label: 'Type', value: doc.doc_type ?? 'circular' },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl p-3 text-center" style={{ background: 'var(--color-bg-secondary)' }}>
            <p className="text-sm font-700" style={{ color: 'var(--color-text-primary)' }}>{value}</p>
            <p className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>{label}</p>
          </div>
        ))}
      </div>

      {/* Source link */}
      {doc.url && (
        <a
          href={doc.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 text-sm font-500 active:opacity-70"
          style={{ color: 'var(--color-accent-amber)' }}
        >
          <ExternalLink size={14} />
          View source document
        </a>
      )}

      {/* Real Version History */}
      <div>
        <p className="text-xs font-700 uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-muted)' }}>
          Version History
        </p>
        {loadingVersions ? (
          <div className="flex items-center gap-2 py-3" style={{ color: 'var(--color-text-muted)' }}>
            <Loader2 size={14} className="animate-spin" />
            <span className="text-xs">Loading versions…</span>
          </div>
        ) : versions.length === 0 ? (
          <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>No version history available</p>
        ) : (
          <div className="space-y-2">
            {versions.map((v, i) => (
              <div
                key={v.id}
                className="flex items-center gap-3 rounded-xl p-3"
                style={{ background: 'var(--color-bg-secondary)' }}
              >
                <GitBranch size={14} style={{ color: 'var(--color-text-muted)' }} />
                <div className="flex-1">
                  <p className="text-xs font-600" style={{ color: 'var(--color-text-primary)' }}>
                    Version {v.version_num}
                  </p>
                  <p className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                    {formatDate(v.ingested_at)} · {v.page_count} pages
                  </p>
                </div>
                {i === 0 && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full font-600" style={{ background: 'rgba(16,185,129,0.1)', color: 'var(--color-severity-low)' }}>Latest</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main Documents Page ───────────────────────────────────────────────────────

export function Documents() {
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<DocumentItem | null>(null)

  // Persistent filter state — survives tab switches
  const { docSource: source, docSort: sort, setDocSource: setSource, setDocSort: setSort } = useFiltersStore()

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getDocuments()
      setDocs(data)
    } catch {
      setError('Failed to load — is the backend running?')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Filter and sort
  const filtered = docs
    .filter(d => source === 'All' || d.regulator === source)
    .sort((a, b) => {
      if (sort === 'Oldest') return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      if (sort === 'Most Versions') return (b.version_count ?? 1) - (a.version_count ?? 1)
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    })

  return (
    <div className="max-w-3xl mx-auto">
      {/* Desktop header */}
      <div className="hidden lg:flex items-center justify-between px-6 py-5">
        <div>
          <h1 className="text-2xl font-800" style={{ color: 'var(--color-text-primary)' }}>Document Library</h1>
          <p className="text-sm mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
            {docs.length} documents indexed
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 text-sm px-4 py-2 rounded-xl active:scale-95 transition-transform"
          style={{ background: 'var(--color-bg-card)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
        >
          <RefreshCw size={15} />
          Refresh
        </button>
      </div>

      {/* Filter bar */}
      <FilterBar source={source} setSource={setSource} sort={sort} setSort={setSort} />

      {/* Content */}
      <div className="px-4 py-4 lg:px-6 space-y-2.5">
        {error && (
          <div className="card p-4 flex items-center gap-3">
            <AlertTriangle size={18} style={{ color: 'var(--color-severity-high)' }} />
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{error}</p>
          </div>
        )}

        {loading
          ? [0, 1, 2, 3, 4].map(i => <DocSkeleton key={i} />)
          : filtered.length === 0
            ? (
              <div className="text-center py-16">
                <Library size={40} className="mx-auto mb-4 opacity-30" />
                <p className="font-600 mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  No documents yet
                </p>
                <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                  Click Sync Regulators on the Dashboard to start ingesting documents
                </p>
              </div>
            )
            : filtered.map(doc => (
              <DocCard key={doc.id} doc={doc} onTap={() => setSelected(doc)} />
            ))
        }
      </div>

      {/* Document Detail Bottom Sheet */}
      <BottomSheet
        isOpen={selected !== null}
        onClose={() => setSelected(null)}
        title={selected?.regulator ? `${selected.regulator} Document` : 'Document Detail'}
        snapHeight={80}
      >
        {selected && <DocDetail doc={selected} />}
      </BottomSheet>
    </div>
  )
}
