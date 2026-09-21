import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import Kiosk from './Kiosk.jsx'

// ?kiosk=1 (or /kiosk) drives the public TV screen instead of the ops dashboard - no router
// dependency needed for one extra view, just a path/query check at boot.
const isKiosk = window.location.pathname.startsWith('/kiosk') || new URLSearchParams(window.location.search).has('kiosk')

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {isKiosk ? <Kiosk /> : <App />}
  </StrictMode>,
)
