import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import Kiosk from './Kiosk.jsx'
import LiveTrack from './LiveTrack.jsx'

// ?kiosk=1 (or /kiosk) drives the public TV screen instead of the ops dashboard - no router
// dependency needed for one extra view, just a path/query check at boot. ?live=1 (or /live)
// is the same pattern for the debug live-track view (see LiveTrack.jsx).
const isKiosk = window.location.pathname.startsWith('/kiosk') || new URLSearchParams(window.location.search).has('kiosk')
const isLiveTrack = window.location.pathname.startsWith('/live') || new URLSearchParams(window.location.search).has('live')

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {isKiosk ? <Kiosk /> : isLiveTrack ? <LiveTrack /> : <App />}
  </StrictMode>,
)
