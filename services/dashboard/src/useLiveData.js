import { useEffect, useState } from 'react'

const WS_URL = (typeof window !== 'undefined' ? window.location.origin : '')
  .replace(/^http/, 'ws') + '/ws'

/** Live occupancy/totals/alerts over the API's WebSocket, with REST fallback if the
 *  socket can't connect (older browsers, restrictive proxies at the venue). */
export function useLiveData() {
  const [live, setLive] = useState(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let ws
    let pollTimer
    let cancelled = false

    const startPolling = () => {
      const poll = async () => {
        try {
          const [occupancy, totals, active_alerts] = await Promise.all([
            fetch('/api/occupancy/current').then((r) => r.json()),
            fetch('/api/totals/today').then((r) => r.json()),
            fetch('/api/alerts/active').then((r) => r.json()),
          ])
          if (!cancelled) setLive({ occupancy, totals, active_alerts })
        } catch {
          // venue Wi-Fi hiccup - just try again next tick
        }
      }
      poll()
      pollTimer = setInterval(poll, 3000)
    }

    try {
      ws = new WebSocket(WS_URL + '/live')
      ws.onopen = () => setConnected(true)
      ws.onmessage = (evt) => !cancelled && setLive(JSON.parse(evt.data))
      ws.onerror = () => ws?.close()
      ws.onclose = () => {
        setConnected(false)
        if (!cancelled) startPolling()
      }
    } catch {
      startPolling()
    }

    return () => {
      cancelled = true
      ws?.close()
      clearInterval(pollTimer)
    }
  }, [])

  return { live, connected }
}

export async function fetchJSON(path) {
  const res = await fetch(`/api${path}`)
  return res.json()
}
