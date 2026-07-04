// api/client.ts — v2.0: Centralized API client with type-safe helpers
import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

// ── Types ─────────────────────────────────────────────────────────────────────

export interface DocumentItem {
  id: number
  regulator: string
  title: string
  url: string
  doc_type?: string
  created_at: string
  version_count?: number
}

export interface DocumentVersionOut {
  id: number
  version_num: number
  content_hash: string
  page_count: number
  ingested_at: string
}

// Alias for backwards compat
export type DocumentOut = DocumentItem

export interface ChangeRecord {
  id: number
  change_type: 'MODIFIED' | 'NEW' | 'REMOVED' | 'UNCHANGED'
  severity: 'High' | 'Medium' | 'Low' | null
  regulator: string | null
  doc_title: string | null
  old_clause: string | null
  new_clause: string | null
  old_section_ref: string | null
  new_section_ref: string | null
  impact_summary: string | null
  affected_area: string | null
  risk_direction: 'increased' | 'decreased' | 'unchanged' | null
  similarity_score: number | null
  detected_at: string
}

// Alias for backwards compat
export type ChangeRecordOut = ChangeRecord

export interface ChangeStats {
  total_changes: number
  changes_this_month: number
  high_severity_count: number
  medium_severity_count: number
  low_severity_count: number
  last_detected_at: string | null
}

export interface DomainDisplay {
  badge: string
  color: string
  description: string
  regulators: string[]
}

export interface PolicyDocumentOut {
  id: number
  filename: string
  page_count: number
  ingested_at: string
  conflict_count: number
  policy_domain: string
  domain_display: DomainDisplay
}

export interface PolicyAnalysisResult {
  policy_id: number
  filename: string
  conflicts: PolicyConflictOut[]
}

export interface PolicyConflictOut {
  id: number
  policy_clause: string
  regulation_clause: string
  conflict: boolean
  explanation: string | null
  suggested_fix: string | null
  conflict_score: number
  regulator: string | null
  doc_title: string | null
  detected_at: string
}

export interface SourceChunk {
  doc_title: string
  regulator: string
  section_ref: string | null
  text: string
  score: number
}

export interface QueryResponse {
  question: string
  answer: string
  sources: SourceChunk[]
  latency_ms: number
}

export interface Bookmark {
  id: number
  document_id?: number
  change_record_id?: number
  created_at: string
  doc_title?: string
  regulator?: string
}

export interface NotificationItem {
  id: number
  type: string
  title: string
  message: string
  read: boolean
  change_record_id?: number
  created_at: string
}

export interface SearchResult {
  type: 'document' | 'change'
  id: number
  title: string
  snippet: string
  score: number
  regulator?: string
}

// ── Documents ─────────────────────────────────────────────────────────────────

export const getDocuments = (regulator?: string): Promise<DocumentItem[]> =>
  api
    .get<DocumentItem[]>('/documents', { params: regulator ? { regulator } : {} })
    .then(r => r.data)

export const getDocumentVersions = (docId: number): Promise<DocumentVersionOut[]> =>
  api.get<DocumentVersionOut[]>(`/documents/${docId}/versions`).then(r => r.data)

// Alias
export const listDocuments = getDocuments

export const triggerIngestion = (
  regulators = ['RBI', 'SEBI'],
  max_docs = 5,
): Promise<unknown> =>
  api.post('/documents/ingest', { regulators, max_docs }).then(r => r.data)

// ── Changes ───────────────────────────────────────────────────────────────────

export const getStats = (): Promise<ChangeStats> =>
  api.get<ChangeStats>('/changes/stats').then(r => r.data)

// Alias
export const getChangeStats = getStats

export const getTimeline = (params?: {
  regulator?: string
  severity?: string
  change_type?: string
  days?: number
  skip?: number
  limit?: number
}): Promise<ChangeRecord[]> =>
  api.get<ChangeRecord[]>('/changes/timeline', { params }).then(r => r.data)

export const getChange = (id: number): Promise<ChangeRecord> =>
  api.get<ChangeRecord>(`/changes/${id}`).then(r => r.data)

// ── Policy ────────────────────────────────────────────────────────────────────

export const uploadPolicy = (file: File): Promise<PolicyDocumentOut> => {
  const formData = new FormData()
  formData.append('file', file)
  return api
    .post<PolicyDocumentOut>('/policy/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then(r => r.data)
}

export const listPolicies = (): Promise<PolicyDocumentOut[]> =>
  api.get<PolicyDocumentOut[]>('/policy').then(r => r.data)

export const checkPolicyConflicts = (policyId: number): Promise<unknown> =>
  api.post(`/policy/${policyId}/check`).then(r => r.data)

export const getPolicyCheckStatus = (policyId: number): Promise<{ policy_id: number; is_processing: boolean; conflict_count: number }> =>
  api.get<{ policy_id: number; is_processing: boolean; conflict_count: number }>(`/policy/${policyId}/status`).then(r => r.data)

export const getPolicyConflicts = (policyId: number): Promise<PolicyConflictOut[]> =>
  api.get<PolicyConflictOut[]>(`/policy/${policyId}/conflicts`).then(r => r.data)

export const exportPolicyPdf = async (policyId: number): Promise<void> => {
  const res = await api.get(`/policy/${policyId}/export-pdf`, { responseType: 'blob' })
  const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `compliance-report-${policyId}.pdf`
  a.click()
  URL.revokeObjectURL(url)
}

// ── RAG Query ─────────────────────────────────────────────────────────────────

export const queryRag = (
  question: string,
  options?: { stream?: boolean; top_k?: number; regulator_filter?: string },
): Promise<QueryResponse> =>
  api
    .post<QueryResponse>('/query', { question, stream: false, ...options })
    .then(r => r.data)

// Stage label map for the progress UI
export const STAGE_LABELS: Record<string, string> = {
  query_analysis:  'Analysing your question…',
  retrieval:       'Searching regulations…',
  confidence_gate: 'Checking retrieval confidence…',
  reasoning:       'Evaluating eligibility rules…',
  synthesis:       'Composing answer…',
  verification:    'Verifying answer accuracy…',
}

/**
 * Streaming RAG query — calls onStage() as each pipeline stage completes,
 * onChunk() for each text token, and returns the full QueryResponse on done.
 */
export async function queryRagStream(
  question: string,
  onStage: (stage: string, label: string, durationMs: number) => void,
  onChunk: (text: string) => void,
  options?: { top_k?: number; regulator_filter?: string },
): Promise<QueryResponse> {
  const response = await fetch('/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, stream: true, ...options }),
  })

  if (!response.ok) throw new Error(`Query failed: ${response.status}`)
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalResult: QueryResponse | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const event = JSON.parse(line.slice(6))
        if (event.type === 'stage') {
          const label = STAGE_LABELS[event.stage] ?? `${event.stage}…`
          onStage(event.stage, label, event.duration_ms)
        } else if (event.type === 'chunk') {
          onChunk(event.text)
        } else if (event.type === 'done') {
          finalResult = {
            question,
            answer: '',  // caller assembled from chunks
            sources: event.sources ?? [],
            latency_ms: event.latency_ms ?? 0,
          }
        }
      } catch { /* skip malformed events */ }
    }
  }

  return finalResult ?? { question, answer: '', sources: [], latency_ms: 0 }
}

// ── Bookmarks ─────────────────────────────────────────────────────────────────

export const getBookmarks = (): Promise<Bookmark[]> =>
  api.get<Bookmark[]>('/bookmarks').then(r => r.data)

export const addBookmark = (params: { document_id?: number; change_record_id?: number }): Promise<Bookmark> =>
  api.post<Bookmark>('/bookmarks', params).then(r => r.data)

export const removeBookmark = (id: number): Promise<void> =>
  api.delete(`/bookmarks/${id}`).then(() => undefined)

// ── Notifications ─────────────────────────────────────────────────────────────

export const getNotifications = (): Promise<NotificationItem[]> =>
  api.get<NotificationItem[]>('/notifications').then(r => r.data)

export const markNotificationRead = (id: number): Promise<void> =>
  api.post(`/notifications/${id}/read`).then(() => undefined)

// ── Fast Keyword Search (BM25 — no LLM) ──────────────────────────────────────

export const keywordSearch = (q: string, type?: 'document' | 'change'): Promise<SearchResult[]> =>
  api
    .get<SearchResult[]>('/search', { params: { q, ...(type ? { type } : {}) } })
    .then(r => r.data)

// ── Evaluation Dashboard ───────────────────────────────────────────────────────

export interface EvalMetrics {
  retrieval_accuracy: number
  answer_accuracy: number
  hallucination_rate: number
  avg_latency_ms: number
  p95_latency_ms: number
}

export interface EvalMetricsResponse {
  run_id?: number
  run_at?: string
  total_cases?: number
  metrics?: EvalMetrics
  deltas?: Partial<EvalMetrics>
  message?: string
}

export interface EvalRunResult {
  question: string
  query_type: string
  retrieved_correct: boolean | null
  answer_score: number | null
  verified: boolean | null
  latency_ms: number | null
  stage_timings: Record<string, number>
  error: string | null
}

export interface EvalHistoryRun {
  run_id: number
  run_at: string
  retrieval_accuracy: number | null
  answer_accuracy: number | null
  hallucination_rate: number | null
  avg_latency_ms: number | null
  p95_latency_ms: number | null
}

export interface EvalTestCase {
  id: number
  question: string
  expected_answer: string
  query_type: string
  expected_chunk_keywords: string[]
}

export const getEvalMetrics = (): Promise<EvalMetricsResponse> =>
  api.get<EvalMetricsResponse>('/evaluation/metrics').then(r => r.data)

export const getEvalResults = (): Promise<{ results: EvalRunResult[]; count: number }> =>
  api.get('/evaluation/results').then(r => r.data)

export const getEvalHistory = (limit = 10): Promise<{ runs: EvalHistoryRun[] }> =>
  api.get('/evaluation/history', { params: { limit } }).then(r => r.data)

export const runEvaluation = (): Promise<{ message: string; status: string }> =>
  api.post('/evaluation/run').then(r => r.data)

export const getEvalStatus = (): Promise<{ running: boolean }> =>
  api.get('/evaluation/status').then(r => r.data)

export const getTestCases = (): Promise<{ test_cases: EvalTestCase[]; count: number }> =>
  api.get('/evaluation/test-cases').then(r => r.data)

export default api
