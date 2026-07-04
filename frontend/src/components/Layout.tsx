// components/Layout.tsx — v2.0: Sidebar on lg+, bottom tab bar + mobile top bar on sm/md
import { useState, useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  LayoutDashboard, GitCompare, Shield, MessageSquare,
  Library, Radar, Sun, Moon, X, Bell, Search, ChevronLeft, BarChart3,
} from 'lucide-react'

const BOTTOM_NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', exact: true },
  { to: '/timeline', icon: GitCompare, label: 'Timeline' },
  { to: '/query', icon: MessageSquare, label: 'Ask' },
  { to: '/policy-check', icon: Shield, label: 'Policy' },
  { to: '/evaluation', icon: BarChart3, label: 'Eval' },
]

const SIDEBAR_NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', exact: true },
  { to: '/timeline', icon: GitCompare, label: 'Change Timeline' },
  { to: '/policy-check', icon: Shield, label: 'Policy Checker' },
  { to: '/query', icon: MessageSquare, label: 'Ask Radar' },
  { to: '/documents', icon: Library, label: 'Document Library' },
  { to: '/evaluation', icon: BarChart3, label: 'Evaluation' },
]

const PAGE_TITLES: Record<string, string> = {
  '/': 'Dashboard',
  '/timeline': 'Change Timeline',
  '/policy-check': 'Policy Checker',
  '/query': 'Ask Radar',
  '/documents': 'Document Library',
  '/search': 'Search',
  '/evaluation': 'Evaluation Dashboard',
}

interface LayoutProps {
  theme: string
  toggleTheme: () => void
  notifCount?: number
}

export function Layout({ theme, toggleTheme, notifCount = 0 }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [searchOpen, setSearchOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const location = useLocation()

  const pageTitle = PAGE_TITLES[location.pathname] ?? 'Radar'
  const isQueryPage = location.pathname === '/query'

  // Detect mobile breakpoint
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 1024)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  return (
    <div
      className="flex h-screen overflow-hidden"
      style={{ background: 'var(--color-bg-primary)' }}
    >
      {/* ── DESKTOP SIDEBAR (lg+) ─────────────────────────────────────────── */}
      {!isMobile && (
        <motion.aside
          animate={{ width: sidebarOpen ? 240 : 64 }}
          transition={{ type: 'spring', stiffness: 300, damping: 30 }}
          className="glass flex flex-col flex-shrink-0 border-r z-20 hidden lg:flex"
          style={{ borderColor: 'var(--color-border)' }}
        >
          {/* Logo */}
          <div className="flex items-center gap-3 px-4 py-5 border-b" style={{ borderColor: 'var(--color-border)' }}>
            <div
              className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center"
              style={{ background: 'var(--color-accent-amber)', boxShadow: '0 0 20px var(--color-accent-amber-glow)' }}
            >
              <Radar size={20} color="#1a0a00" strokeWidth={2.5} />
            </div>
            {sidebarOpen && (
              <motion.div
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.05 }}
              >
                <div className="font-700 text-sm leading-tight gradient-text">Regulatory</div>
                <div className="font-700 text-sm leading-tight gradient-text">Change Radar</div>
              </motion.div>
            )}
          </div>

          {/* Nav items */}
          <nav className="flex-1 py-4 px-2 space-y-1 overflow-hidden">
            {SIDEBAR_NAV.map(({ to, icon: Icon, label, exact }) => (
              <NavLink
                key={to}
                to={to}
                end={exact}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 group relative ${
                    isActive ? 'text-amber-400' : 'text-slate-400 hover:text-slate-200'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <motion.div
                        layoutId="nav-indicator"
                        className="absolute inset-0 rounded-xl"
                        style={{ background: 'var(--color-accent-amber-dim)', border: '1px solid rgba(245,158,11,0.2)' }}
                        transition={{ type: 'spring', stiffness: 500, damping: 35 }}
                      />
                    )}
                    <Icon size={18} className="flex-shrink-0 relative z-10" strokeWidth={isActive ? 2.5 : 2} />
                    {sidebarOpen && (
                      <span className="text-sm font-500 relative z-10 whitespace-nowrap">{label}</span>
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </nav>

          {/* Bottom controls */}
          <div className="px-2 py-4 border-t space-y-1" style={{ borderColor: 'var(--color-border)' }}>
            <button
              onClick={toggleTheme}
              className="flex items-center gap-3 w-full px-3 py-2.5 rounded-xl transition-all duration-200 text-slate-400 hover:text-slate-200 hover:bg-white/5"
            >
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
              {sidebarOpen && <span className="text-sm">Toggle Theme</span>}
            </button>
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="flex items-center gap-3 w-full px-3 py-2.5 rounded-xl transition-all duration-200 text-slate-400 hover:text-slate-200 hover:bg-white/5"
            >
              <ChevronLeft size={18} style={{ transform: sidebarOpen ? 'none' : 'rotate(180deg)', transition: 'transform 0.3s' }} />
              {sidebarOpen && <span className="text-sm">Collapse</span>}
            </button>
          </div>
        </motion.aside>
      )}

      {/* ── MAIN CONTENT AREA ─────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* ── MOBILE TOP BAR (sm/md only) ──────────────────────────────────── */}
        {isMobile && !isQueryPage && (
          <div
            className="flex items-center justify-between px-4 py-3 flex-shrink-0 border-b lg:hidden"
            style={{
              background: 'var(--color-bg-card)',
              borderColor: 'var(--color-border)',
              paddingTop: 'max(12px, env(safe-area-inset-top))',
            }}
          >
            <div className="flex items-center gap-2">
              <div
                className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ background: 'var(--color-accent-amber)' }}
              >
                <Radar size={14} color="#1a0a00" strokeWidth={2.5} />
              </div>
              <h1 className="font-700 text-base" style={{ color: 'var(--color-text-primary)' }}>
                {pageTitle}
              </h1>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setSearchOpen(true)}
                className="w-10 h-10 flex items-center justify-center rounded-xl active:scale-95 transition-transform"
                style={{ color: 'var(--color-text-secondary)' }}
                id="mobile-search-btn"
              >
                <Search size={19} />
              </button>
              <button
                onClick={toggleTheme}
                className="w-10 h-10 flex items-center justify-center rounded-xl active:scale-95 transition-transform"
                style={{ color: 'var(--color-text-secondary)' }}
                id="mobile-theme-btn"
              >
                {theme === 'dark' ? <Sun size={19} /> : <Moon size={19} />}
              </button>
              <button
                className="w-10 h-10 flex items-center justify-center rounded-xl active:scale-95 transition-transform relative"
                style={{ color: 'var(--color-text-secondary)' }}
                id="mobile-notif-btn"
              >
                <Bell size={19} />
                {notifCount > 0 && (
                  <span
                    className="absolute top-1.5 right-1.5 w-4 h-4 rounded-full text-[9px] font-700 flex items-center justify-center"
                    style={{ background: 'var(--color-severity-high)', color: 'white' }}
                  >
                    {notifCount > 9 ? '9+' : notifCount}
                  </span>
                )}
              </button>
            </div>
          </div>
        )}

        {/* ── PAGE CONTENT ─────────────────────────────────────────────────── */}
        <main
          className="flex-1 overflow-auto"
          style={{ paddingBottom: isMobile && !isQueryPage ? 'calc(64px + env(safe-area-inset-bottom))' : 0 }}
        >
          <Outlet />
        </main>
      </div>

      {/* ── MOBILE BOTTOM TAB BAR (sm/md only) ──────────────────────────────── */}
      {isMobile && !isQueryPage && (
        <nav
          className="fixed bottom-0 left-0 right-0 z-30 border-t lg:hidden"
          style={{
            background: 'var(--color-bg-card)',
            borderColor: 'var(--color-border)',
            backdropFilter: 'blur(20px)',
            paddingBottom: 'env(safe-area-inset-bottom)',
          }}
        >
          <div className="flex items-center justify-around h-16">
            {BOTTOM_NAV.map(({ to, icon: Icon, label, exact }) => (
              <NavLink
                key={to}
                to={to}
                end={exact}
                className={({ isActive }) =>
                  `flex flex-col items-center justify-center gap-0.5 flex-1 h-full transition-all duration-150 active:scale-90 ${
                    isActive ? '' : ''
                  }`
                }
                id={`bottom-nav-${label.toLowerCase()}`}
              >
                {({ isActive }) => (
                  <>
                    <div
                      className="w-10 h-7 flex items-center justify-center rounded-full transition-all duration-150"
                      style={{
                        background: isActive ? 'var(--color-accent-amber-dim)' : 'transparent',
                      }}
                    >
                      <Icon
                        size={20}
                        strokeWidth={isActive ? 2.5 : 1.8}
                        style={{ color: isActive ? 'var(--color-accent-amber)' : 'var(--color-text-muted)' }}
                      />
                    </div>
                    <span
                      className="text-[10px] font-500"
                      style={{ color: isActive ? 'var(--color-accent-amber)' : 'var(--color-text-muted)' }}
                    >
                      {label}
                    </span>
                  </>
                )}
              </NavLink>
            ))}
          </div>
        </nav>
      )}

      {/* ── MOBILE SEARCH OVERLAY ─────────────────────────────────────────── */}
      <AnimatePresence>
        {searchOpen && (
          <motion.div
            className="fixed inset-0 z-50 flex flex-col"
            style={{ background: 'var(--color-bg-primary)' }}
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.2 }}
          >
            <div
              className="flex items-center gap-3 px-4 py-3 border-b"
              style={{
                borderColor: 'var(--color-border)',
                paddingTop: 'max(12px, env(safe-area-inset-top))',
              }}
            >
              <input
                autoFocus
                className="input flex-1"
                placeholder="Search regulations, circulars…"
                id="mobile-search-input"
              />
              <button
                onClick={() => setSearchOpen(false)}
                className="w-10 h-10 flex items-center justify-center"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                <X size={20} />
              </button>
            </div>
            <div className="flex-1 flex items-center justify-center">
              <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                Type to search across all regulations
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
