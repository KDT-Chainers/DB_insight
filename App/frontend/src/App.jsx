import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LandingLogin from './pages/LandingLogin'
import InitialSetup from './pages/InitialSetup'
import MainSearchMode from './pages/MainSearchMode'
import MainSearchModeResult from './pages/MainSearchModeResult'
import MainSearchModeResultSpecific from './pages/MainSearchModeResultSpecific'
import MainAIMode from './pages/MainAIMode'
import MainAIModeResult from './pages/MainAIModeResult'
import MainAIModeResultSpecific from './pages/MainAIModeResultSpecific'
import Settings from './pages/Settings'
import DataIndexing from './pages/DataIndexing'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingLogin />} />
        <Route path="/setup" element={<InitialSetup />} />
        <Route path="/search" element={<MainSearchMode />} />
        <Route path="/search/results" element={<MainSearchModeResult />} />
        <Route path="/search/results/:id" element={<MainSearchModeResultSpecific />} />
        <Route path="/ai" element={<MainAIMode />} />
        <Route path="/ai/results" element={<MainAIModeResult />} />
        <Route path="/ai/results/:id" element={<MainAIModeResultSpecific />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/data" element={<DataIndexing />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
