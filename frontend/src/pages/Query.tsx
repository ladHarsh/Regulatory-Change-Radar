// pages/Query.tsx — v3.1: Real-time stage-progress via streaming SSE
import { useState, useRef, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Send, BookOpen, Loader2, Radar, Trash2, ArrowLeft, MoreVertical, Plus } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { queryRagStream } from '../api/client'
import type { SourceChunk } from '../api/client'
import { BottomSheet } from '../components/BottomSheet'
import { useChatStore, type ChatMessage } from '../store'

const SUGGESTED_QUERIES = [
  'What changed in the latest RBI circular?',
  'Summarise SEBI insider trading regulations',
  'What are the new KYC requirements?',
]

// ── Source Chip ──────────────────────────────────────────────────────────────

function SourceChipRow({
  sources,
  onChipTap,
}: {
  sources: SourceChunk[]
  onChipTap: (s: SourceChunk) => void
}) {
  if (!sources || sources.length === 0) return null
  return (
    <div className="flex gap-2 mt-2 overflow-x-auto pb-1" style={{ scrollbarWidth: 'none' }}>
      {sources.slice(0, 5).map((s, i) => (
        <button
          key={i}
          onClick={() => onChipTap(s)}
          className="flex-shrink-0 flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border active:scale-95 transition-transform"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-secondary)',
          }}
        >
          <BookOpen size={10} />
          {s.doc_title ? s.doc_title.slice(0, 20) + (s.doc_title.length > 20 ? '…' : '') : `Source ${i + 1}`}
        </button>
      ))}
    </div>
  )
}

// ── Message Bubble ────────────────────────────────────────────────────────────

function MessageBubble({
  msg,
  onSourceTap,
}: {
  msg: ChatMessage
  onSourceTap: (s: SourceChunk) => void
}) {
  const isUser = msg.role === 'user'

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}
    >
      {!isUser && (
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mr-2 mt-0.5"
          style={{ background: 'var(--color-accent-amber)' }}
        >
          <Radar size={13} color="#1a0a00" />
        </div>
      )}

      <div className={`max-w-[85%] lg:max-w-[75%]`}>
        <div
          className="rounded-2xl px-4 py-3 text-sm leading-relaxed"
          style={{
            background: isUser ? 'var(--color-accent-amber)' : 'var(--color-bg-card)',
            color: isUser ? '#1a0a00' : 'var(--color-text-secondary)',
            border: isUser ? 'none' : '1px solid var(--color-border)',
            borderBottomRightRadius: isUser ? 6 : undefined,
            borderBottomLeftRadius: !isUser ? 6 : undefined,
          }}
        >
          {msg.text}
        </div>

        {!isUser && msg.sources && msg.sources.length > 0 && (
          <SourceChipRow sources={msg.sources} onChipTap={onSourceTap} />
        )}

        {!isUser && msg.latency_ms && (
          <p className="text-[10px] mt-1 ml-1" style={{ color: 'var(--color-text-muted)' }}>
            {msg.latency_ms}ms
          </p>
        )}
      </div>
    </motion.div>
  )
}

// ── Main Query Page ───────────────────────────────────────────────────────────

export function Query() {
  // Persistent state — survives tab switches
  const { messages, addMessage, clearMessages } = useChatStore()

  const navigate = useNavigate()
  const [showMenu, setShowMenu] = useState(false)
  const [showClearConfirm, setShowClearConfirm] = useState(false)

  // Transient UI state — fine to reset on mount
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [stageLabel, setStageLabel] = useState('Searching regulations\u2026')
  const [selectedSource, setSelectedSource] = useState<SourceChunk | null>(null)
  const [viewportHeight, setViewportHeight] = useState(window.innerHeight)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Handle mobile keyboard via visualViewport
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const handle = () => setViewportHeight(vv.height)
    vv.addEventListener('resize', handle)
    return () => vv.removeEventListener('resize', handle)
  }, [])

  const scrollToBottom = useCallback(() => {
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }, [])

  // Scroll on new messages
  useEffect(() => {
    if (messages.length > 0) scrollToBottom()
  }, [messages.length, scrollToBottom])

  const send = useCallback(async (text: string) => {
    if (!text.trim() || loading) return
    const q = text.trim()
    setInput('')

    const userMsg: ChatMessage = { id: Date.now().toString(), role: 'user', text: q }
    addMessage(userMsg)
    setLoading(true)
    setStageLabel('Searching regulations\u2026')
    scrollToBottom()

    try {
      let assembled = ''

      const res = await queryRagStream(
        q,
        (_stage, label, _ms) => {
          setStageLabel(label)
        },
        (chunk) => {
          assembled += chunk
        },
      )

      const botMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        text: assembled.trim() || res.answer || 'No answer returned.',
        sources: res.sources,
        latency_ms: res.latency_ms,
      }
      addMessage(botMsg)
    } catch (err) {
      console.error('Query API error:', err)
      addMessage({
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        text: 'Sorry, I couldn\'t reach the backend. Please ensure the API server is running.',
      })
    } finally {
      setLoading(false)
      scrollToBottom()
    }
  }, [loading, scrollToBottom, addMessage])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(input)
    }
  }

  const isEmpty = messages.length === 0

  return (
    <div
      className="flex flex-col overflow-hidden"
      style={{ height: `${viewportHeight}px`, maxHeight: '100dvh' }}
    >
      {/* Mobile Header (visible only on mobile) */}
      <div
        className="flex lg:hidden items-center justify-between px-4 py-3 border-b flex-shrink-0"
        style={{
          background: 'var(--color-bg-card)',
          borderColor: 'var(--color-border)',
          paddingTop: 'max(12px, env(safe-area-inset-top))',
        }}
      >
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/')}
            className="w-8 h-8 rounded-lg flex items-center justify-center active:scale-90 transition-transform"
            style={{ color: 'var(--color-text-primary)' }}
          >
            <ArrowLeft size={20} />
          </button>
          <div>
            <h2 className="font-700 text-sm leading-none" style={{ color: 'var(--color-text-primary)' }}>Ask Radar</h2>
            <span className="text-[10px] text-muted leading-none">SEBI · RBI · IRDAI</span>
          </div>
        </div>
        <div className="relative">
          <button
            onClick={() => setShowMenu(!showMenu)}
            className="w-8 h-8 rounded-lg flex items-center justify-center active:scale-90 transition-transform"
            style={{ color: 'var(--color-text-primary)' }}
          >
            <MoreVertical size={20} />
          </button>
          
          {/* Dropdown Menu */}
          <AnimatePresence>
            {showMenu && (
              <>
                <div className="fixed inset-0 z-30" onClick={() => setShowMenu(false)} />
                <motion.div
                  initial={{ opacity: 0, scale: 0.95, y: -5 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95, y: -5 }}
                  transition={{ duration: 0.1 }}
                  className="absolute right-0 mt-1 w-44 rounded-xl border z-40 p-1.5 shadow-xl"
                  style={{
                    background: 'var(--color-bg-card)',
                    borderColor: 'var(--color-border)',
                  }}
                >
                  <button
                    onClick={() => {
                      setShowMenu(false)
                      setShowClearConfirm(true)
                    }}
                    className="flex items-center gap-2 w-full text-left px-3 py-2 text-xs rounded-lg hover:bg-white/5 active:bg-white/10"
                    style={{ color: 'var(--color-severity-high)' }}
                  >
                    <Trash2 size={13} />
                    Clear Chat
                  </button>
                  <button
                    onClick={() => {
                      setShowMenu(false)
                      clearMessages()
                    }}
                    className="flex items-center gap-2 w-full text-left px-3 py-2 text-xs rounded-lg hover:bg-white/5 active:bg-white/10"
                    style={{ color: 'var(--color-text-primary)' }}
                  >
                    <Plus size={13} />
                    New Chat
                  </button>
                </motion.div>
              </>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Desktop header */}
      <div className="hidden lg:flex items-center justify-between px-6 pt-6 pb-2 flex-shrink-0">
        <div>
          <h1 className="text-2xl font-800" style={{ color: 'var(--color-text-primary)' }}>Ask Radar</h1>
          <p className="text-sm mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
            Ask any question about RBI, SEBI, or IRDAI regulations
          </p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={() => setShowClearConfirm(true)}
            className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-xl active:scale-95 transition-transform"
            style={{ background: 'var(--color-bg-card)', color: 'var(--color-text-muted)', border: '1px solid var(--color-border)' }}
            id="clear-chat-btn"
          >
            <Trash2 size={13} />
            Clear chat
          </button>
        )}
      </div>

      {/* ── Message thread ───────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto overscroll-contain px-4 py-4 lg:px-6">
        {isEmpty ? (
          /* Empty state — suggested queries */
          <div className="flex flex-col items-center justify-center h-full pb-8 gap-5">
            <div
              className="w-16 h-16 rounded-2xl flex items-center justify-center"
              style={{ background: 'var(--color-accent-amber)', boxShadow: '0 0 30px var(--color-accent-amber-glow)' }}
            >
              <Radar size={32} color="#1a0a00" />
            </div>
            <div className="text-center">
              <h2 className="font-700 text-lg mb-1" style={{ color: 'var(--color-text-primary)' }}>Ask Radar</h2>
              <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                Instant answers from RBI, SEBI &amp; IRDAI regulations
              </p>
            </div>

            {/* Suggested queries */}
            <div className="w-full max-w-sm space-y-2">
              {SUGGESTED_QUERIES.map((q, i) => (
                <button
                  key={i}
                  onClick={() => send(q)}
                  className="w-full text-left text-sm px-4 py-3 rounded-xl border active:scale-[0.99] transition-transform"
                  style={{
                    background: 'var(--color-bg-card)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-secondary)',
                  }}
                  id={`suggested-query-${i}`}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map(msg => (
              <MessageBubble key={msg.id} msg={msg} onSourceTap={setSelectedSource} />
            ))}
            {loading && (
              <div className="flex justify-start mb-3">
                <div
                  className="w-7 h-7 rounded-full flex items-center justify-center mr-2"
                  style={{ background: 'var(--color-accent-amber)' }}
                >
                  <Radar size={13} color="#1a0a00" />
                </div>
                <div
                  className="rounded-2xl px-4 py-3 flex items-center gap-2"
                  style={{ background: 'var(--color-bg-card)', border: '1px solid var(--color-border)' }}
                >
                  <Loader2 size={14} className="animate-spin" style={{ color: 'var(--color-accent-amber)' }} />
                  <AnimatePresence mode="wait">
                    <motion.span
                      key={stageLabel}
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -4 }}
                      transition={{ duration: 0.2 }}
                      className="text-sm"
                      style={{ color: 'var(--color-text-muted)' }}
                    >
                      {stageLabel}
                    </motion.span>
                  </AnimatePresence>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </>
        )}
      </div>

      {/* ── Input bar — sticky above keyboard ──────────────────── */}
      <div
        className="flex-shrink-0 px-4 py-3 border-t"
        style={{
          background: 'var(--color-bg-card)',
          borderColor: 'var(--color-border)',
          paddingBottom: 'max(12px, env(safe-area-inset-bottom))',
        }}
      >
        <div className="flex items-end gap-2 max-w-3xl mx-auto">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about any regulation…"
            rows={1}
            className="flex-1 resize-none rounded-xl px-4 py-2.5 text-sm outline-none transition-all"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-primary)',
              maxHeight: 120,
              lineHeight: 1.5,
            }}
            id="query-input"
          />
          <button
            onClick={() => send(input)}
            disabled={!input.trim() || loading}
            className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 active:scale-90 transition-transform disabled:opacity-40"
            style={{ background: 'var(--color-accent-amber)' }}
            id="send-query-btn"
          >
            <Send size={16} color="#1a0a00" />
          </button>
        </div>
        <p className="text-[10px] text-center mt-1.5" style={{ color: 'var(--color-text-muted)' }}>
          Enter to send · Shift+Enter for new line
        </p>
      </div>

      {/* ── Source Detail Bottom Sheet ─────────────────────────── */}
      <BottomSheet
        isOpen={selectedSource !== null}
        onClose={() => setSelectedSource(null)}
        title="Source"
        snapHeight={60}
      >
        {selectedSource && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 flex-wrap">
              {selectedSource.doc_title && (
                <span
                  className="text-xs px-2.5 py-1 rounded-full font-600"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)' }}
                >
                  {selectedSource.doc_title}
                </span>
              )}
              {selectedSource.section_ref && (
                <span
                  className="text-xs px-2.5 py-1 rounded-full font-500"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-muted)' }}
                >
                  § {selectedSource.section_ref}
                </span>
              )}
              {selectedSource.score != null && (
                <span
                  className="text-xs px-2.5 py-1 rounded-full font-500"
                  style={{ background: 'rgba(245,158,11,0.1)', color: 'var(--color-accent-amber)' }}
                >
                  Score: {(selectedSource.score * 100).toFixed(0)}%
                </span>
              )}
            </div>
            <div
              className="rounded-xl p-4 text-sm leading-relaxed"
              style={{
                background: 'var(--color-bg-secondary)',
                color: 'var(--color-text-secondary)',
                fontFamily: 'monospace',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {selectedSource.text}
            </div>
          </div>
        )}
      </BottomSheet>

      {/* Clear Confirmation Modal */}
      <AnimatePresence>
        {showClearConfirm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="w-full max-w-sm rounded-2xl p-5 border text-center"
              style={{
                background: 'var(--color-bg-card)',
                borderColor: 'var(--color-border)',
              }}
            >
              <h3 className="text-base font-700 text-primary mb-2" style={{ color: 'var(--color-text-primary)' }}>Clear conversation?</h3>
              <p className="text-xs text-muted mb-5 leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                This will wipe your entire chat history. This action cannot be undone.
              </p>
              <div className="flex gap-3 justify-center">
                <button
                  onClick={() => setShowClearConfirm(false)}
                  className="flex-1 py-2 px-4 rounded-xl text-xs font-600 border transition-transform active:scale-95"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-secondary)',
                  }}
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    clearMessages()
                    setShowClearConfirm(false)
                  }}
                  className="flex-1 py-2 px-4 rounded-xl text-xs font-600 text-white transition-transform active:scale-95"
                  style={{
                    background: 'var(--color-severity-high)',
                  }}
                >
                  Clear
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
