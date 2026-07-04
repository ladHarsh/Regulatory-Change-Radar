// App.tsx — Root application with routing and theme management
import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Layout } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Timeline } from './pages/Timeline'
import { PolicyCheck } from './pages/PolicyCheck'
import { Query } from './pages/Query'
import { Documents } from './pages/Documents'
import { Evaluation } from './pages/Evaluation'

const pageTransition = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
  transition: { duration: 0.2, ease: 'easeInOut' },
}

function PageWrapper({ children }: { children: React.ReactNode }) {
  return (
    <motion.div {...pageTransition} className="h-full">
      {children}
    </motion.div>
  )
}

export default function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('radar-theme') as 'dark' | 'light') ?? 'dark'
  })

  useEffect(() => {
    document.documentElement.classList.toggle('light', theme === 'light')
    localStorage.setItem('radar-theme', theme)
  }, [theme])

  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark')

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout theme={theme} toggleTheme={toggleTheme} />}>
          <Route path="/" element={<PageWrapper><Dashboard /></PageWrapper>} />
          <Route path="/timeline" element={<PageWrapper><Timeline /></PageWrapper>} />
          <Route path="/policy-check" element={<PageWrapper><PolicyCheck /></PageWrapper>} />
          <Route path="/query" element={<PageWrapper><Query /></PageWrapper>} />
          <Route path="/documents" element={<PageWrapper><Documents /></PageWrapper>} />
          <Route path="/evaluation" element={<PageWrapper><Evaluation /></PageWrapper>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
