/**
 * store/index.ts — Global Zustand state store
 *
 * Why: React Router unmounts page components on navigation, destroying all
 * useState() values. We lift persistent state here so it survives tab switches.
 *
 * Three slices:
 *   useChatStore     — Ask Radar chat history (messages)
 *   usePolicyStore   — Policy Checker file + analysis state
 *   useFiltersStore  — Timeline + Documents filter selections
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { PolicyAnalysisResult, SourceChunk } from '../api/client'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  sources?: SourceChunk[]
  latency_ms?: number
}

// ── Chat Store — Ask Radar history ────────────────────────────────────────────

interface ChatState {
  messages: ChatMessage[]
  addMessage: (msg: ChatMessage) => void
  clearMessages: () => void
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      messages: [],
      addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
      clearMessages: () => set({ messages: [] }),
    }),
    { name: 'radar-chat' }
  )
)

// ── Policy Store — Policy Checker analysis state ───────────────────────────────

interface PolicyState {
  file: { name: string; size: number } | null
  step: number  // -1=idle, 0-3=steps, 4=done
  results: PolicyAnalysisResult | null
  error: string
  policyId: number | null
  setFile: (file: { name: string; size: number } | null) => void
  setStep: (step: number) => void
  setResults: (results: PolicyAnalysisResult | null) => void
  setError: (error: string) => void
  setPolicyId: (id: number | null) => void
  reset: () => void
}

export const usePolicyStore = create<PolicyState>()(
  persist(
    (set) => ({
      file: null,
      step: -1,
      results: null,
      error: '',
      policyId: null,
      setFile: (file) => set({ file }),
      setStep: (step) => set({ step }),
      setResults: (results) => set({ results }),
      setError: (error) => set({ error }),
      setPolicyId: (policyId) => set({ policyId }),
      reset: () => set({ file: null, step: -1, results: null, error: '', policyId: null }),
    }),
    { name: 'radar-policy' }
  )
)

// ── Filters Store — Timeline + Documents filter selections ────────────────────

interface FiltersState {
  // Timeline filters
  timelineSeverity: string
  timelineChangeType: string
  timelineRegulator: string
  setTimelineSeverity: (v: string) => void
  setTimelineChangeType: (v: string) => void
  setTimelineRegulator: (v: string) => void
  // Documents filters
  docSource: string
  docSort: string
  setDocSource: (v: string) => void
  setDocSort: (v: string) => void
}

export const useFiltersStore = create<FiltersState>()(
  persist(
    (set) => ({
      timelineSeverity: 'All',
      timelineChangeType: 'All',
      timelineRegulator: 'All',
      setTimelineSeverity: (v) => set({ timelineSeverity: v }),
      setTimelineChangeType: (v) => set({ timelineChangeType: v }),
      setTimelineRegulator: (v) => set({ timelineRegulator: v }),
      docSource: 'All',
      docSort: 'Newest',
      setDocSource: (v) => set({ docSource: v }),
      setDocSort: (v) => set({ docSort: v }),
    }),
    { name: 'radar-filters' }
  )
)
