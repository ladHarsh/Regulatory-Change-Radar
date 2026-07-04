// components/BottomSheet.tsx — Reusable Framer Motion drag-to-dismiss bottom sheet
// Used for: change detail, citation detail, document version history, conflict detail
import { useRef, useEffect } from 'react'
import { motion, AnimatePresence, useDragControls } from 'framer-motion'

interface BottomSheetProps {
  isOpen: boolean
  onClose: () => void
  title?: string
  children: React.ReactNode
  /** Height as % of viewport. Default 80 */
  snapHeight?: number
}

export function BottomSheet({ isOpen, onClose, title, children, snapHeight = 80 }: BottomSheetProps) {
  const dragControls = useDragControls()
  const sheetRef = useRef<HTMLDivElement>(null)

  // Lock body scroll when sheet is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [isOpen])

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            className="fixed inset-0 z-40"
            style={{ background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)' }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />

          {/* Sheet */}
          <motion.div
            ref={sheetRef}
            className="fixed left-0 right-0 bottom-0 z-50 flex flex-col"
            style={{
              background: 'var(--color-bg-card)',
              borderRadius: '20px 20px 0 0',
              border: '1px solid var(--color-border)',
              maxHeight: `${snapHeight}vh`,
              paddingBottom: 'env(safe-area-inset-bottom)',
            }}
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'spring', stiffness: 400, damping: 40 }}
            drag="y"
            dragControls={dragControls}
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.5 }}
            onDragEnd={(_, info) => {
              if (info.velocity.y > 300 || info.offset.y > 150) {
                onClose()
              }
            }}
          >
            {/* Drag handle — touch-friendly 44px target */}
            <div
              className="flex justify-center pt-3 pb-1 cursor-grab active:cursor-grabbing flex-shrink-0"
              style={{ minHeight: 44 }}
              onPointerDown={(e) => dragControls.start(e)}
            >
              <div
                className="rounded-full"
                style={{ width: 36, height: 4, background: 'var(--color-border-strong)' }}
              />
            </div>

            {/* Title */}
            {title && (
              <div
                className="px-5 pb-3 flex-shrink-0 border-b"
                style={{ borderColor: 'var(--color-border)' }}
              >
                <h3 className="font-600 text-base" style={{ color: 'var(--color-text-primary)' }}>
                  {title}
                </h3>
              </div>
            )}

            {/* Content — scrollable */}
            <div className="flex-1 overflow-y-auto overscroll-contain px-5 py-4">
              {children}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
