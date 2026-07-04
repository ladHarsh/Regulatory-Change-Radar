// pages/Evaluation.tsx — RAG Pipeline Evaluation Dashboard
// Tracks 5 metrics: Retrieval Accuracy, Answer Accuracy, Hallucination Rate, Avg Latency, P95 Latency
import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import {
  BarChart3, Play, RefreshCw, CheckCircle2, XCircle,
  TrendingUp, TrendingDown, Minus, Clock, Target,
  Brain, Shield, Zap, AlertTriangle,
  FlaskConical, Info,
} from 'lucide-react'
import {
  getEvalMetrics, getEvalResults, getEvalHistory, runEvaluation,
  getEvalStatus,
} from '../api/client'
import type { EvalMetricsResponse, EvalRunResult, EvalHistoryRun } from '../api/client'
import { BottomSheet } from '../components/BottomSheet'

// ── Helpers ───────────────────────────────────────────────────────────────────

const pct = (v: number | null | undefined) =>
  v == null ? '—' : `${(v * 100).toFixed(1)}%`
const score = (v: number | null | undefined) =>
  v == null ? '—' : v.toFixed(2)
const ms = (v: number | null | undefined) =>
  v == null ? '—' : `${Math.round(v)}ms`

function DeltaBadge({ delta, invert = false }: { delta?: number | null; invert?: boolean }) {
  if (delta == null || Math.abs(delta) < 0.001) {
    return <span className="eval-delta eval-delta--neutral"><Minus size={10} /> —</span>
  }
  const positive = invert ? delta < 0 : delta > 0
  return (
    <span className={`eval-delta ${positive ? 'eval-delta--up' : 'eval-delta--down'}`}>
      {positive ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
      {Math.abs(delta * 100).toFixed(1)}%
    </span>
  )
}

// ── Stage Bar Chart ───────────────────────────────────────────────────────────

function StageBarChart({ results }: { results: EvalRunResult[] }) {
  const stages = ['query_analysis', 'retrieval', 'confidence_gate', 'reasoning', 'synthesis', 'verification']
  const stageLabels: Record<string, string> = {
    query_analysis: 'Query Analysis',
    retrieval: 'Retrieval',
    confidence_gate: 'Conf. Gate',
    reasoning: 'Reasoning',
    synthesis: 'Synthesis',
    verification: 'Verification',
  }
  const stageColors: Record<string, string> = {
    query_analysis: '#6366f1',
    retrieval: '#8b5cf6',
    confidence_gate: '#a78bfa',
    reasoning: '#f59e0b',
    synthesis: '#10b981',
    verification: '#ef4444',
  }

  if (!results.length) return null

  // Compute average per stage across all results
  const avgs: Record<string, number> = {}
  stages.forEach(s => {
    const vals = results
      .map(r => r.stage_timings?.[s])
      .filter((v): v is number => v != null)
    avgs[s] = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0
  })

  const maxVal = Math.max(...Object.values(avgs), 1)

  return (
    <div className="eval-chart-container">
      <h3 className="eval-section-title">
        <Clock size={14} /> Avg Stage Latency Breakdown
      </h3>
      <div className="eval-bars">
        {stages.map(s => (
          <div key={s} className="eval-bar-row">
            <span className="eval-bar-label">{stageLabels[s]}</span>
            <div className="eval-bar-track">
              <motion.div
                className="eval-bar-fill"
                initial={{ width: 0 }}
                animate={{ width: `${(avgs[s] / maxVal) * 100}%` }}
                transition={{ duration: 0.6, ease: 'easeOut' }}
                style={{ background: stageColors[s] }}
              />
            </div>
            <span className="eval-bar-value">{Math.round(avgs[s])}ms</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── History Sparkline ─────────────────────────────────────────────────────────

function Sparkline({
  runs,
  field,
  width = 80,
  height = 28,
}: {
  runs: EvalHistoryRun[]
  field: keyof EvalHistoryRun
  width?: number
  height?: number
}) {
  if (runs.length < 2) return <span className="eval-sparkline-empty">Not enough runs</span>
  const vals = runs
    .slice()
    .reverse()
    .map(r => r[field] as number | null)
    .filter((v): v is number => v != null)

  if (!vals.length) return null

  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const range = max - min || 1
  const W = width, H = height

  const points = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * W
    const y = H - ((v - min) / range) * H
    return `${x},${y}`
  }).join(' ')

  return (
    <svg width={W} height={H} className="eval-sparkline">
      <polyline
        points={points}
        fill="none"
        stroke="var(--color-accent-primary)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {vals.map((v, i) => (
        <circle
          key={i}
          cx={(i / (vals.length - 1)) * W}
          cy={H - ((v - min) / range) * H}
          r="2"
          fill="var(--color-accent-primary)"
        />
      ))}
    </svg>
  )
}

// ── Per-Question Table ────────────────────────────────────────────────────────

function ResultsTable({ results }: { results: EvalRunResult[] }) {
  const [expanded, setExpanded] = useState<number | null>(null)

  if (!results.length) {
    return (
      <div className="eval-empty-table">
        <FlaskConical size={24} style={{ opacity: 0.4 }} />
        <p>No results yet. Run the evaluation suite to see per-question breakdowns.</p>
      </div>
    )
  }

  const typeBadge = (t: string) => {
    const colors: Record<string, string> = {
      factual: '#6366f1', eligibility: '#f59e0b', scenario: '#10b981', comparison: '#8b5cf6',
    }
    return (
      <span className="eval-type-badge" style={{ background: `${colors[t] || '#6366f1'}22`, color: colors[t] || '#6366f1' }}>
        {t}
      </span>
    )
  }

  return (
    <div className="eval-table-wrap">
      <table className="eval-table">
        <thead>
          <tr>
            <th style={{ width: '40%' }}>Question</th>
            <th>Type</th>
            <th>Retrieved</th>
            <th>Score</th>
            <th>Verified</th>
            <th>Latency</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r, i) => (
            <>
              <tr
                key={i}
                className={`eval-table-row ${expanded === i ? 'eval-table-row--expanded' : ''}`}
                onClick={() => setExpanded(expanded === i ? null : i)}
              >
                <td className="eval-table-question">
                  {r.error && <AlertTriangle size={12} className="eval-error-icon" />}
                  {r.question}
                </td>
                <td>{typeBadge(r.query_type)}</td>
                <td>
                  {r.retrieved_correct == null ? '—' : r.retrieved_correct
                    ? <CheckCircle2 size={14} style={{ color: '#10b981' }} />
                    : <XCircle size={14} style={{ color: '#ef4444' }} />}
                </td>
                <td>
                  {r.answer_score == null ? '—' : (
                    <span className="eval-score-pill" style={{
                      background: r.answer_score >= 4 ? '#10b98122' : r.answer_score >= 3 ? '#f59e0b22' : '#ef444422',
                      color: r.answer_score >= 4 ? '#10b981' : r.answer_score >= 3 ? '#f59e0b' : '#ef4444',
                    }}>
                      {r.answer_score.toFixed(1)}/5
                    </span>
                  )}
                </td>
                <td>
                  {r.verified == null ? '—' : r.verified
                    ? <span style={{ color: '#10b981', fontSize: '0.75rem', fontWeight: 600 }}>✓ Passed</span>
                    : <span style={{ color: '#ef4444', fontSize: '0.75rem', fontWeight: 600 }}>✗ Failed</span>}
                </td>
                <td style={{ color: 'var(--color-text-muted)', fontSize: '0.8rem' }}>
                  {r.latency_ms ? `${r.latency_ms}ms` : '—'}
                </td>
              </tr>
              {expanded === i && (
                <tr key={`${i}-exp`} className="eval-table-expand">
                  <td colSpan={6}>
                    <div className="eval-expand-content">
                      {r.error && (
                        <div className="eval-expand-error">
                          <AlertTriangle size={12} /> Error: {r.error}
                        </div>
                      )}
                      {Object.keys(r.stage_timings || {}).length > 0 && (
                        <div className="eval-expand-timings">
                          <strong>Stage timings:</strong>{' '}
                          {Object.entries(r.stage_timings)
                            .filter(([k]) => k !== 'total')
                            .map(([k, v]) => `${k}: ${v}ms`)
                            .join(' | ')}
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main Evaluation Page ──────────────────────────────────────────────────────

export function Evaluation() {
  const [metrics, setMetrics] = useState<EvalMetricsResponse | null>(null)
  const [results, setResults] = useState<EvalRunResult[]>([])
  const [history, setHistory] = useState<EvalHistoryRun[]>([])
  const [running, setRunning] = useState(false)
  const [loading, setLoading] = useState(true)
  const [runMsg, setRunMsg] = useState('')
  const [activeMetricId, setActiveMetricId] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    try {
      const [m, r, h] = await Promise.all([
        getEvalMetrics(),
        getEvalResults(),
        getEvalHistory(8),
      ])
      setMetrics(m)
      setResults(r.results || [])
      setHistory(h.runs || [])
    } catch (e) {
      console.error('Failed to load eval data', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  // Poll status while running
  useEffect(() => {
    if (!running) return
    const interval = setInterval(async () => {
      try {
        const { running: r } = await getEvalStatus()
        if (!r) {
          setRunning(false)
          setRunMsg('Evaluation complete!')
          await loadData()
          setTimeout(() => setRunMsg(''), 4000)
        }
      } catch {}
    }, 3000)
    return () => clearInterval(interval)
  }, [running, loadData])

  const handleRun = async () => {
    if (running) return
    try {
      setRunMsg('Starting evaluation suite...')
      await runEvaluation()
      setRunning(true)
      setRunMsg('Running 25 test cases through the pipeline...')
    } catch (e: any) {
      if (e?.response?.status === 409) {
        setRunMsg('An evaluation is already running.')
      } else {
        setRunMsg('Failed to start evaluation.')
      }
      setTimeout(() => setRunMsg(''), 3000)
    }
  }

  const m = metrics?.metrics

  const metricCards = [
    {
      id: 'retrieval',
      label: 'Retrieval Accuracy',
      sublabel: 'Recall@5',
      icon: Target,
      value: pct(m?.retrieval_accuracy),
      delta: metrics?.deltas?.retrieval_accuracy,
      color: '#6366f1',
      invert: false,
      info: 'Was the correct chunk in the top-5 retrieved results?',
    },
    {
      id: 'accuracy',
      label: 'Answer Accuracy',
      sublabel: 'LLM-as-judge 1-5',
      icon: Brain,
      value: score(m?.answer_accuracy),
      delta: metrics?.deltas?.answer_accuracy,
      color: '#10b981',
      invert: false,
      info: 'Average LLM judge score (1=wrong, 5=perfect)',
    },
    {
      id: 'hallucination',
      label: 'Hallucination Rate',
      sublabel: '% unverified answers',
      icon: Shield,
      value: pct(m?.hallucination_rate),
      delta: metrics?.deltas?.hallucination_rate,
      color: '#ef4444',
      invert: true,  // lower is better
      info: '% of answers where Verification Agent returned verified=false',
    },
    {
      id: 'latency',
      label: 'Avg Latency',
      sublabel: 'per request',
      icon: Zap,
      value: ms(m?.avg_latency_ms),
      delta: metrics?.deltas?.avg_latency_ms,
      color: '#f59e0b',
      invert: true,  // lower is better
      info: 'Average end-to-end response time across all test cases',
    },
    {
      id: 'p95',
      label: 'P95 Latency',
      sublabel: '95th percentile',
      icon: Clock,
      value: ms(m?.p95_latency_ms),
      delta: null,
      color: '#8b5cf6',
      invert: true,
      info: '95th percentile latency — worst-case user experience',
    },
  ]

  return (
    <div className="eval-page">
      {/* Header */}
      <div className="eval-header">
        <div className="eval-header-left">
          <div className="eval-header-icon">
            <BarChart3 size={20} />
          </div>
          <div>
            <h1 className="eval-title">Evaluation Dashboard</h1>
            <p className="eval-subtitle">
              {metrics?.run_at
                ? `Last run: ${new Date(metrics.run_at).toLocaleString()} · ${metrics.total_cases} test cases`
                : 'No evaluation runs yet'}
            </p>
          </div>
        </div>
        <div className="eval-header-right">
          {runMsg && (
            <motion.span
              className="eval-run-msg"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              {runMsg}
            </motion.span>
          )}
          <button
            id="run-eval-btn"
            className={`eval-run-btn ${running ? 'eval-run-btn--running' : ''}`}
            onClick={handleRun}
            disabled={running}
          >
            {running ? (
              <><RefreshCw size={14} className="eval-spin" /> Running…</>
            ) : (
              <><Play size={14} /> Run Evaluation Suite</>
            )}
          </button>
          <button className="eval-refresh-btn" onClick={loadData} title="Refresh">
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {loading ? (
        <div className="eval-loading">
          <RefreshCw size={24} className="eval-spin" />
          <span>Loading evaluation data…</span>
        </div>
      ) : metrics?.message ? (
        /* No runs yet state */
        <div className="eval-no-runs">
          <FlaskConical size={48} style={{ opacity: 0.3 }} />
          <h2>No Evaluation Runs Yet</h2>
          <p>Click "Run Evaluation Suite" to run all 25 test cases through the full RAG pipeline and compute metrics.</p>
          <div className="eval-test-count">
            <span>25 labeled test cases ready</span>
            <span>5 metrics tracked</span>
            <span>Factual + Eligibility + Scenario</span>
          </div>
        </div>
      ) : (
        <div className="eval-content">
          {/* Metric Cards */}
          <div className="eval-metrics-grid">
            {metricCards.map((card, i) => (
              <motion.div
                key={card.id}
                className="eval-metric-card"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.07 }}
                onClick={() => setActiveMetricId(card.id)}
                style={{ '--card-accent': card.color, cursor: 'pointer' } as any}
              >
                <div className="eval-metric-header">
                  <div className="eval-metric-icon" style={{ background: `${card.color}22`, color: card.color }}>
                    <card.icon size={16} />
                  </div>
                  <div className="eval-metric-info" title={card.info}>
                    <Info size={11} />
                  </div>
                </div>
                <div className="eval-metric-value">{card.value}</div>
                <div className="eval-metric-label">{card.label}</div>
                <div className="eval-metric-sub">
                  <span>{card.sublabel}</span>
                  <DeltaBadge delta={typeof card.delta === 'number' ? card.delta : null} invert={card.invert} />
                </div>
                <div className="eval-metric-sparkline">
                  {history.length > 1 && (
                    <Sparkline
                      runs={history}
                      field={card.id === 'retrieval' ? 'retrieval_accuracy'
                        : card.id === 'accuracy' ? 'answer_accuracy'
                        : card.id === 'hallucination' ? 'hallucination_rate'
                        : card.id === 'latency' ? 'avg_latency_ms'
                        : 'p95_latency_ms'}
                    />
                  )}
                </div>
              </motion.div>
            ))}
          </div>

          {/* Stage Latency Chart */}
          {results.length > 0 && <StageBarChart results={results} />}

          {/* Per-question table */}
          <div className="eval-table-section">
            <h3 className="eval-section-title">
              <FlaskConical size={14} /> Per-Question Results
              <span className="eval-table-count">{results.length} questions</span>
            </h3>
            <ResultsTable results={results} />
          </div>
        </div>
      )}
      {/* Metric Detail Bottom Sheet */}
      {(() => {
        const activeCard = metricCards.find(c => c.id === activeMetricId)
        if (!activeCard) return null

        const historyField = activeMetricId === 'retrieval' ? 'retrieval_accuracy'
          : activeMetricId === 'accuracy' ? 'answer_accuracy'
          : activeMetricId === 'hallucination' ? 'hallucination_rate'
          : activeMetricId === 'latency' ? 'avg_latency_ms'
          : 'p95_latency_ms'

        // Prepare filtered question results
        let sortedResults = [...results]
        if (activeMetricId === 'latency' || activeMetricId === 'p95') {
          // Sort by slowest first
          sortedResults.sort((a, b) => (b.latency_ms ?? 0) - (a.latency_ms ?? 0))
        } else if (activeMetricId === 'retrieval') {
          // Sort failed retrievals first
          sortedResults.sort((a, b) => (a.retrieved_correct ? 1 : 0) - (b.retrieved_correct ? 1 : 0))
        } else if (activeMetricId === 'hallucination') {
          // Sort unverified first
          sortedResults.sort((a, b) => (a.verified ? 1 : 0) - (b.verified ? 1 : 0))
        }

        return (
          <BottomSheet
            isOpen={activeMetricId !== null}
            onClose={() => setActiveMetricId(null)}
            title={activeCard.label}
            snapHeight={85}
          >
            <div className="space-y-6 pb-6">
              {/* Stat Summary */}
              <div className="flex items-center justify-between p-4 rounded-2xl border" style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)' }}>
                <div>
                  <div className="text-3xl font-800" style={{ color: 'var(--color-text-primary)' }}>{activeCard.value}</div>
                  <div className="text-xs text-muted mt-1">{activeCard.sublabel}</div>
                </div>
                <div className="eval-metric-icon" style={{ width: 44, height: 44, background: `${activeCard.color}22`, color: activeCard.color }}>
                  <activeCard.icon size={22} />
                </div>
              </div>

              {/* Description */}
              <div className="text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                <p>{activeCard.info}</p>
              </div>

              {/* Large History Chart */}
              {history.length > 1 && (
                <div className="p-4 rounded-2xl border flex flex-col gap-2" style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)' }}>
                  <div className="text-xs font-700 uppercase tracking-wider text-muted">Historical Trend</div>
                  <div className="h-32 flex items-center justify-center pt-2">
                    <Sparkline runs={history} field={historyField} width={280} height={100} />
                  </div>
                </div>
              )}

              {/* Run History List */}
              <div className="p-4 rounded-2xl border space-y-3" style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)' }}>
                <div className="text-xs font-700 uppercase tracking-wider text-muted">Run History Log</div>
                <div className="space-y-1">
                  {history.map((run, idx) => {
                    const val = run[historyField]
                    const displayVal = activeMetricId === 'accuracy' ? score(val) : activeMetricId.includes('latency') ? ms(val) : pct(val)
                    return (
                      <div key={idx} className="flex justify-between items-center text-xs py-2 border-b border-white/5 last:border-b-0">
                        <span style={{ color: 'var(--color-text-secondary)' }}>
                          Run #{run.run_id} ({new Date(run.run_at).toLocaleDateString()})
                        </span>
                        <span className="font-700" style={{ color: 'var(--color-text-primary)' }}>
                          {displayVal}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Question Breakdown Table */}
              {sortedResults.length > 0 && (
                <div className="p-4 rounded-2xl border space-y-3" style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)' }}>
                  <div className="text-xs font-700 uppercase tracking-wider text-muted">Per-Question Impact</div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs text-left border-collapse">
                      <thead>
                        <tr className="border-b border-white/10">
                          <th className="py-2 pr-2 text-muted" style={{ width: '70%' }}>Question</th>
                          <th className="py-2 text-muted text-right">Value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sortedResults.slice(0, 10).map((r, idx) => {
                          let valText = '—'
                          let valColor = ''
                          if (activeMetricId === 'retrieval') {
                            valText = r.retrieved_correct ? 'Passed' : 'Failed'
                            valColor = r.retrieved_correct ? '#10b981' : '#ef4444'
                          } else if (activeMetricId === 'accuracy') {
                            valText = r.answer_score != null ? `${r.answer_score.toFixed(1)}/5` : '—'
                            valColor = r.answer_score != null && r.answer_score >= 4 ? '#10b981' : r.answer_score != null && r.answer_score >= 3 ? '#f59e0b' : '#ef4444'
                          } else if (activeMetricId === 'hallucination') {
                            valText = r.verified ? 'Verified' : 'Flagged'
                            valColor = r.verified ? '#10b981' : '#ef4444'
                          } else if (activeMetricId === 'latency' || activeMetricId === 'p95') {
                            valText = r.latency_ms ? `${r.latency_ms}ms` : '—'
                            valColor = r.latency_ms && r.latency_ms < 8000 ? '#10b981' : r.latency_ms && r.latency_ms < 15000 ? '#f59e0b' : '#ef4444'
                          }
                          return (
                            <tr key={idx} className="border-b border-white/5 last:border-b-0">
                              <td className="py-2.5 pr-2 text-primary font-500 line-clamp-1" style={{ color: 'var(--color-text-secondary)' }}>
                                {r.question}
                              </td>
                              <td className="py-2.5 font-700 text-right" style={{ color: valColor }}>
                                {valText}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          </BottomSheet>
        )
      })()}
    </div>
  )
}
