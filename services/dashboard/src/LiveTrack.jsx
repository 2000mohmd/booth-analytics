import { useEffect, useState } from 'react'
import { useLiveTracks } from './useLiveData'

const DEBUG_VIDEO_POLL_MS = 200

// Debug-only page: shows tracking working live. Default view is the anonymized skeleton -
// only bbox coords/zone/track id ever leave ingestion (services/metrics_engine/store.py's
// live_tracks table, services/api/main.py's /tracks/live + /ws/tracks) - keeping the "zero
// video retention" boundary from README.md intact by default.
//
// The "raw video" toggle below is a SEPARATE, deliberate exception: it only shows anything if
// ingestion was started with DEBUG_VIDEO_STREAM=1 (services/ingestion/pipeline.py), which
// publishes downscaled JPEG frames with box overlays already burned in, polled here from
// services/api/main.py's /debug/video/{camera_id}. Local dev/test only - see that endpoint's
// docstring. Never enable DEBUG_VIDEO_STREAM at a real venue.
// Open with ?live=1 or /live (see main.jsx).

const ZONE_COLORS = { aisle: '#facc15', stand: '#34d399', table: '#60a5fa' }
const TRACK_COLOR = '#f472b6'
const VIEWBOX_FALLBACK = 1280

function SkeletonView({ cam }) {
  const vbW = cam.frame_w || VIEWBOX_FALLBACK
  const vbH = cam.frame_h || (VIEWBOX_FALLBACK * 0.75)
  return (
    <svg viewBox={`0 0 ${vbW} ${vbH}`} className="w-full rounded-lg bg-black" style={{ aspectRatio: `${vbW} / ${vbH}` }}>
      {Object.entries(cam.zones || {}).map(([name, pts]) => (
        pts.length >= 3 && (
          <polygon
            key={name}
            points={pts.map((p) => p.join(',')).join(' ')}
            fill={(ZONE_COLORS[name] || '#888') + '22'}
            stroke={ZONE_COLORS[name] || '#888'}
            strokeWidth={2}
          />
        )
      ))}
      {cam.tracks.map((t) => (
        <g key={t.track_id}>
          <rect
            x={t.x1} y={t.y1} width={t.x2 - t.x1} height={t.y2 - t.y1}
            fill="none" stroke={TRACK_COLOR} strokeWidth={3} rx={4}
          />
          <text x={t.x1} y={t.y1 - 6} fill={TRACK_COLOR} fontSize={vbW * 0.018} fontFamily="monospace">
            {t.track_id}{t.zone ? ` · ${t.zone}` : ''}
          </text>
        </g>
      ))}
    </svg>
  )
}

// Polls single frames instead of an MJPEG <img>: Chromium doesn't reliably render
// multipart/x-mixed-replace in an <img>, so it froze on the first frame.
function DebugVideo({ cameraId }) {
  const [src, setSrc] = useState(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    let cancelled = false
    let current = null
    let timer

    const tick = async () => {
      try {
        const res = await fetch(`/api/debug/video/${cameraId}`, { cache: 'no-store' })
        if (cancelled) return
        if (!res.ok) {
          setMissing(true)
        } else {
          const url = URL.createObjectURL(await res.blob())
          if (cancelled) return URL.revokeObjectURL(url)
          if (current) URL.revokeObjectURL(current)
          current = url
          setSrc(url)
          setMissing(false)
        }
      } catch {
        // dev server restart / network blip - next tick retries
      }
      if (!cancelled) timer = setTimeout(tick, DEBUG_VIDEO_POLL_MS)
    }
    tick()

    return () => {
      cancelled = true
      clearTimeout(timer)
      if (current) URL.revokeObjectURL(current)
    }
  }, [cameraId])

  if (missing && !src) {
    return (
      <div className="w-full aspect-video rounded-lg bg-black flex items-center justify-center text-xs text-neutral-500 text-center px-4">
        No debug video - start ingestion with DEBUG_VIDEO_STREAM=1
      </div>
    )
  }
  return <img src={src || undefined} alt={`raw debug feed for ${cameraId}`} className="w-full rounded-lg bg-black" />
}

function CameraPanel({ cameraId, cam, showRawVideo }) {
  const stale = !cam.frame_w

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-3 min-w-0">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm uppercase tracking-wide text-neutral-400">{cameraId}</h2>
        <span className={`text-xs px-2 py-0.5 rounded-full ${stale ? 'bg-neutral-800 text-neutral-500' : 'bg-emerald-900 text-emerald-300'}`}>
          {stale ? 'no signal' : `${cam.tracks.length} tracked`}
        </span>
      </div>
      {showRawVideo ? (
        <DebugVideo cameraId={cameraId} />
      ) : (
        <SkeletonView cam={cam} />
      )}
    </div>
  )
}

export default function LiveTrack() {
  const { tracks, connected } = useLiveTracks()
  const [showRawVideo, setShowRawVideo] = useState(false)
  const cameras = Object.entries(tracks || {})

  return (
    <div className="min-h-screen px-4 py-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-xl font-semibold">Live Track (debug)</h1>
        <span className={`text-xs px-2 py-1 rounded-full ${connected ? 'bg-emerald-900 text-emerald-300' : 'bg-neutral-800 text-neutral-400'}`}>
          {connected ? 'live' : 'polling'}
        </span>
      </div>
      <p className="text-xs text-neutral-500 mb-3">
        Default view is positions/zones only - no camera video, per this project's
        zero-video-retention design (README.md).
      </p>
      <label className="flex items-center gap-2 text-xs text-amber-400 mb-4 select-none">
        <input type="checkbox" checked={showRawVideo} onChange={(e) => setShowRawVideo(e.target.checked)} />
        Show raw video (local dev/test only - requires ingestion started with DEBUG_VIDEO_STREAM=1;
        never enable this at a real venue)
      </label>
      {!cameras.length && <p className="text-neutral-500 text-sm">No cameras reporting yet.</p>}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {cameras.map(([cameraId, cam]) => (
          <CameraPanel key={cameraId} cameraId={cameraId} cam={cam} showRawVideo={showRawVideo} />
        ))}
      </div>
    </div>
  )
}
