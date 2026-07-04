// pages/PolicyCheck.tsx — v3.0: Persistent state via Zustand, robust validation
import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useDropzone } from 'react-dropzone'
import {
  Upload, Shield, CheckCircle, Loader2, AlertTriangle,
  Download, FileText,
} from 'lucide-react'
import { uploadPolicy, exportPolicyPdf, checkPolicyConflicts, getPolicyCheckStatus, getPolicyConflicts } from '../api/client'
import { BottomSheet } from '../components/BottomSheet'
import { DiffToggle } from '../components/DiffView'
import { usePolicyStore } from '../store'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Conflict {
  id: number
  policy_clause: string
  regulation_clause: string
  conflict: boolean
  explanation?: string
  suggested_fix?: string
  conflict_score: number
}

// ── Step indicator ─────────────────────────────────────────────────────────────

const STEPS = ['Classifying', 'Parsing', 'Retrieving', 'Analyzing']

interface StepperProps {
  current: number
  total?: number
}

function Stepper({ current }: StepperProps) {
  return (
    <div className="space-y-2">
      {STEPS.map((label, i) => {
        const done = i < current
        const active = i === current
        return (
          <div key={label} className="flex items-center gap-3">
            <div
              className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 transition-all duration-300"
              style={{
                background: done
                  ? 'var(--color-severity-low)'
                  : active
                    ? 'var(--color-accent-amber)'
                    : 'var(--color-bg-secondary)',
                border: `2px solid ${done ? 'var(--color-severity-low)' : active ? 'var(--color-accent-amber)' : 'var(--color-border)'}`,
              }}
            >
              {done
                ? <CheckCircle size={12} color="white" />
                : active
                  ? <Loader2 size={12} color="#1a0a00" className="animate-spin" />
                  : <span className="text-[9px] font-700" style={{ color: 'var(--color-text-muted)' }}>{i + 1}</span>
              }
            </div>
            <span
              className="text-sm font-500"
              style={{
                color: done || active ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
              }}
            >
              {label}
              {active && <span className="text-xs ml-1.5" style={{ color: 'var(--color-text-muted)' }}>in progress…</span>}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── Conflict Card ─────────────────────────────────────────────────────────────

interface ConflictCardProps {
  conflict: Conflict
  index: number
  onTap: () => void
}

function ConflictCard({ conflict, index, onTap }: ConflictCardProps) {
  const score = conflict.conflict_score
  const scoreColor = score > 0.66 ? 'var(--color-severity-high)' : score > 0.33 ? 'var(--color-severity-medium)' : 'var(--color-severity-low)'

  return (
    <button
      onClick={onTap}
      className="w-full text-left card p-4 active:scale-[0.99] transition-all duration-150 hover:border-amber-500/30"
      id={`conflict-card-${index}`}
    >
      {/* Score bar — full width above content */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] font-700 uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
            Conflict Score
          </span>
          <span className="text-xs font-700" style={{ color: scoreColor }}>
            {(score * 100).toFixed(0)}%
          </span>
        </div>
        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--color-bg-secondary)' }}>
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${score * 100}%` }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="h-full rounded-full"
            style={{ background: scoreColor }}
          />
        </div>
      </div>

      {/* Policy clause excerpt */}
      <p
        className="text-xs leading-relaxed line-clamp-2 mb-2"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        <span className="font-600" style={{ color: 'var(--color-text-muted)' }}>Your policy: </span>
        {conflict.policy_clause.slice(0, 120)}{conflict.policy_clause.length > 120 ? '…' : ''}
      </p>

      {conflict.conflict && (
        <div className="flex items-center gap-1.5">
          <AlertTriangle size={12} style={{ color: 'var(--color-severity-high)' }} />
          <span className="text-[10px] font-600" style={{ color: 'var(--color-severity-high)' }}>
            Conflict detected — tap for details
          </span>
        </div>
      )}
    </button>
  )
}

// ── Main PolicyCheck Page ─────────────────────────────────────────────────────

export function PolicyCheck() {
  const {
    file: storeFile,
    step,
    results,
    error,
    policyId,
    setFile: setStoreFile,
    setStep,
    setResults,
    setError,
    setPolicyId,
  } = usePolicyStore()

  const [localFile, setLocalFile] = useState<File | null>(null)
  const [selectedConflict, setSelectedConflict] = useState<Conflict | null>(null)
  const [policyDomain, setPolicyDomain] = useState<{ domain: string; display: { badge: string; color: string; description: string; regulators: string[] } } | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const startPolling = (id: number) => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
    }
    let attempts = 0
    intervalRef.current = setInterval(async () => {
      try {
        attempts++
        // Progress stepper based on time/attempts
        if (attempts >= 3) {
          setStep(3) // Analyzing
        }
        
        const status = await getPolicyCheckStatus(id)
        if (!status.is_processing) {
          if (intervalRef.current) clearInterval(intervalRef.current)
          const conflictsResult = await getPolicyConflicts(id)
          setResults({
            policy_id: id,
            filename: storeFile?.name || 'Policy Document',
            conflicts: conflictsResult,
          })
          // Fetch updated policy record to get domain info set by classifier
          try {
            const { listPolicies } = await import('../api/client')
            const policies = await listPolicies()
            const pol = policies.find(p => p.id === id)
            if (pol?.policy_domain && pol.domain_display?.badge) {
              setPolicyDomain({ domain: pol.policy_domain, display: pol.domain_display })
            }
          } catch { /* non-critical */ }
          setStep(4) // Done
        }
      } catch (err: any) {
        if (intervalRef.current) clearInterval(intervalRef.current)
        const errorMsg = err?.response?.data?.detail || 'Analysis checking failed — backend connection lost'
        setError(errorMsg)
        setStep(-1)
      }
    }, 2000)
  }

  // Resume polling on mount if we were processing
  useEffect(() => {
    if (step >= 0 && step < 4 && policyId !== null) {
      startPolling(policyId)
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
    }
  }, [step, policyId])

  const handleRun = async () => {
    if (!localFile) return
    
    // Client-side size check (20 MB limit)
    if (localFile.size > 20 * 1024 * 1024) {
      setError('File too large — maximum allowed size is 20 MB. Please upload a smaller document.')
      return
    }

    setError('')
    setResults(null)
    setStep(0) // Parsing

    try {
      // Step 0: Upload & Parse
      const doc = await uploadPolicy(localFile)
      setPolicyId(doc.id)

      // Store domain display info if available (populated after first check run)
      if (doc.policy_domain && doc.domain_display?.badge) {
        setPolicyDomain({ domain: doc.policy_domain, display: doc.domain_display })
      }
      
      // Step 1: Trigger analysis task (backend classifies domain, then checks)
      setStep(1)
      await checkPolicyConflicts(doc.id)
      
      // Step 2 & 3: Retrieving & Analyzing (Poll for results)
      setStep(2)
      startPolling(doc.id)

    } catch (err: any) {
      const errorMsg = err?.response?.data?.detail || 'Analysis failed — check backend connection'
      setError(errorMsg)
      setStep(-1)
    }
  }

  const handleExport = async () => {
    const id = results?.policy_id || policyId
    if (!id) return
    try {
      await exportPolicyPdf(id)
    } catch {
      alert('PDF export failed')
    }
  }

  // Dropzone — tap-friendly on mobile
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/pdf': ['.pdf'] },
    maxFiles: 1,
    onDrop: (files) => {
      if (files[0]) {
        const f = files[0]
        if (f.size > 20 * 1024 * 1024) {
          setError('File too large — maximum allowed size is 20 MB. Please upload a smaller document.')
          return
        }
        setLocalFile(f)
        setStoreFile({ name: f.name, size: f.size })
        setResults(null)
        setStep(-1)
        setError('')
        setPolicyId(null)
      }
    },
  })

  const displayedFile = localFile || storeFile
  const conflicts: Conflict[] = (results as any)?.conflicts ?? []
  const isRunning = step >= 0 && step < 4

  return (
    <div className="max-w-2xl mx-auto px-4 py-4 lg:px-6 lg:py-6 pb-28 lg:pb-6">
      {/* Desktop header */}
      <div className="hidden lg:block mb-6">
        <h1 className="text-2xl font-800" style={{ color: 'var(--color-text-primary)' }}>Policy Checker</h1>
        <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>
          Upload your internal policy to detect conflicts with live regulatory data
        </p>
      </div>

      {/* ── Upload Zone ───────────────────────────────────────── */}
      <div
        {...getRootProps()}
        className={`rounded-2xl border-2 border-dashed transition-all duration-200 cursor-pointer active:scale-[0.99] ${isDragActive ? 'border-amber-400' : ''}`}
        style={{
          borderColor: isDragActive ? 'var(--color-accent-amber)' : 'var(--color-border)',
          background: isDragActive ? 'var(--color-accent-amber-dim)' : 'var(--color-bg-card)',
          padding: displayedFile ? '16px' : '32px 24px',
        }}
        id="policy-upload-zone"
      >
        <input {...getInputProps()} />

        {displayedFile ? (
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(245,158,11,0.12)' }}
            >
              <FileText size={20} style={{ color: 'var(--color-accent-amber)' }} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-600 truncate" style={{ color: 'var(--color-text-primary)' }}>
                {displayedFile.name}
              </p>
              <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                {(displayedFile.size / 1024).toFixed(0)} KB · PDF
              </p>
            </div>
            <span className="text-xs px-2 py-1 rounded-lg" style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-muted)' }}>
              Change
            </span>
          </div>
        ) : (
          <div className="text-center">
            <div
              className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4"
              style={{ background: 'rgba(245,158,11,0.1)' }}
            >
              <Upload size={28} style={{ color: 'var(--color-accent-amber)' }} />
            </div>
            {/* Desktop text */}
            <p className="hidden sm:block font-600 mb-1" style={{ color: 'var(--color-text-primary)' }}>
              Drag & drop or click to upload
            </p>
            {/* Mobile text */}
            <p className="sm:hidden font-600 mb-1" style={{ color: 'var(--color-text-primary)' }}>
              Tap to upload policy document
            </p>
            <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>PDF files only</p>
          </div>
        )}
      </div>

      {/* ── Processing Stepper ────────────────────────────────── */}
      <AnimatePresence>
        {isRunning && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="card p-5 mt-4 overflow-hidden"
          >
            <p className="text-sm font-600 mb-4" style={{ color: 'var(--color-text-primary)' }}>
              Analyzing your policy…
            </p>
            <Stepper current={step} />
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Error ─────────────────────────────────────────────── */}
      {error && (
        <div className="card p-4 mt-4 flex items-center gap-3">
          <AlertTriangle size={18} style={{ color: 'var(--color-severity-high)' }} />
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{error}</p>
        </div>
      )}

      {/* ── Results ───────────────────────────────────────────── */}
      <AnimatePresence>
        {results && step === 4 && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-5 space-y-4"
          >
            {/* Summary */}
            <div className="card p-5">
              <div className="flex items-center gap-3 mb-3">
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center"
                  style={{ background: 'rgba(245,158,11,0.1)' }}
                >
                  <Shield size={20} style={{ color: 'var(--color-accent-amber)' }} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-700" style={{ color: 'var(--color-text-primary)' }}>
                    Analysis Complete
                  </p>
                  <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    {conflicts.length} conflict{conflicts.length !== 1 ? 's' : ''} found
                  </p>
                </div>
                <button
                  onClick={handleExport}
                  className="ml-auto flex items-center gap-1.5 text-xs px-3 py-2 rounded-xl active:scale-95 transition-transform"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                  id="export-pdf-btn"
                >
                  <Download size={13} />
                  Export PDF
                </button>
              </div>

              {/* Domain badge */}
              {policyDomain && (
                <div
                  className="flex items-center gap-2 px-3 py-2 rounded-xl mt-1"
                  style={{ background: `${policyDomain.display.color}18`, border: `1px solid ${policyDomain.display.color}40` }}
                  title={`Analysis restricted to: ${policyDomain.display.regulators.join(', ')} — ${policyDomain.display.description}`}
                >
                  <span
                    className="text-[10px] font-800 px-1.5 py-0.5 rounded-md"
                    style={{ background: policyDomain.display.color, color: '#fff', letterSpacing: '0.05em' }}
                  >
                    {policyDomain.display.badge}
                  </span>
                  <span className="text-xs font-600" style={{ color: policyDomain.display.color }}>
                    {policyDomain.display.description}
                  </span>
                  <span className="text-xs ml-auto" style={{ color: 'var(--color-text-muted)' }}>
                    Checked against: {policyDomain.display.regulators.join(', ')}
                  </span>
                </div>
              )}
            </div>

            {/* Conflict list */}
            {conflicts.length > 0 && (
              <div className="space-y-2.5">
                <p className="text-sm font-700" style={{ color: 'var(--color-text-primary)' }}>
                  Detected Conflicts
                </p>
                {conflicts.map((c, i) => (
                  <ConflictCard
                    key={c.id}
                    conflict={c}
                    index={i}
                    onTap={() => setSelectedConflict(c)}
                  />
                ))}
              </div>
            )}

            {conflicts.length === 0 && (
              <div className="card p-8 text-center">
                <CheckCircle size={32} className="mx-auto mb-3" style={{ color: 'var(--color-severity-low)' }} />
                <p className="font-600 mb-1" style={{ color: 'var(--color-text-primary)' }}>No conflicts detected</p>
                <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                  Your policy appears compliant with current regulations
                </p>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── STICKY BOTTOM CTA (mobile) ────────────────────────── */}
      <div
        className="fixed bottom-0 left-0 right-0 px-4 py-3 lg:hidden border-t z-20"
        style={{
          background: 'var(--color-bg-card)',
          borderColor: 'var(--color-border)',
          paddingBottom: 'calc(12px + env(safe-area-inset-bottom))',
          // Only show above bottom tab bar
          bottom: 'calc(64px + env(safe-area-inset-bottom))',
        }}
      >
        <button
          onClick={handleRun}
          disabled={!localFile || isRunning}
          className="btn-primary w-full py-3.5 rounded-xl font-600 flex items-center justify-center gap-2 active:scale-[0.98] transition-transform disabled:opacity-50"
          id="run-check-btn-mobile"
        >
          {isRunning
            ? <><Loader2 size={18} className="animate-spin" /> Analyzing…</>
            : <><Shield size={18} /> Run Conflict Check</>
          }
        </button>
      </div>

      {/* Desktop CTA */}
      {localFile && !isRunning && (
        <button
          onClick={handleRun}
          className="btn-primary hidden lg:flex items-center justify-center gap-2 w-full mt-4 py-3.5 rounded-xl font-600 active:scale-[0.99] transition-transform"
          id="run-check-btn-desktop"
        >
          <Shield size={18} /> Run Conflict Check
        </button>
      )}

      {/* ── Conflict Detail Bottom Sheet ───────────────────────── */}
      <BottomSheet
        isOpen={selectedConflict !== null}
        onClose={() => setSelectedConflict(null)}
        title="Conflict Detail"
        snapHeight={88}
      >
        {selectedConflict && (
          <div className="space-y-5">
            {/* Score */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-700 uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
                  Conflict Score
                </p>
                <span
                  className="text-sm font-700"
                  style={{
                    color: selectedConflict.conflict_score > 0.66
                      ? 'var(--color-severity-high)'
                      : selectedConflict.conflict_score > 0.33
                        ? 'var(--color-severity-medium)'
                        : 'var(--color-severity-low)',
                  }}
                >
                  {(selectedConflict.conflict_score * 100).toFixed(0)}%
                </span>
              </div>
              <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-bg-secondary)' }}>
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${selectedConflict.conflict_score * 100}%`,
                    background: selectedConflict.conflict_score > 0.66
                      ? 'var(--color-severity-high)'
                      : selectedConflict.conflict_score > 0.33
                        ? 'var(--color-severity-medium)'
                        : 'var(--color-severity-low)',
                  }}
                />
              </div>
            </div>

            {/* Clause diff */}
            <div>
              <p className="text-xs font-700 uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-muted)' }}>
                Clause Comparison
              </p>
              <DiffToggle
                oldText={selectedConflict.policy_clause}
                newText={selectedConflict.regulation_clause}
                showDiff
              />
            </div>

            {/* Explanation */}
            {selectedConflict.explanation && (
              <div>
                <p className="text-xs font-700 uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-muted)' }}>
                  AI Explanation
                </p>
                <div
                  className="rounded-xl p-4 text-sm leading-relaxed"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
                >
                  {selectedConflict.explanation}
                </div>
              </div>
            )}

            {/* Suggested fix */}
            {selectedConflict.suggested_fix && (
              <div>
                <p className="text-xs font-700 uppercase tracking-wide mb-2" style={{ color: 'var(--color-severity-low)' }}>
                  Suggested Fix
                </p>
                <div
                  className="rounded-xl p-4 text-sm leading-relaxed"
                  style={{ background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.2)', color: 'var(--color-text-secondary)' }}
                >
                  {selectedConflict.suggested_fix}
                </div>
              </div>
            )}
          </div>
        )}
      </BottomSheet>
    </div>
  )
}
