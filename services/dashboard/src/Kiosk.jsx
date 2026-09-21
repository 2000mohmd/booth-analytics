import { useEffect, useState } from 'react'
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fetchJSON, useLiveData } from './useLiveData'

// Public-facing TV display for the booth floor - not the ops dashboard (services/dashboard/src/App.jsx).
// Shows only aggregate counts and charts, never raw video or anything that identifies a visitor -
// keeps the "zero video retention, anonymous events only" principle intact even on a public screen.
// Open with ?kiosk=1 (see main.jsx) on whatever device drives the TV.

const COLORS = ['#6ee7ff', '#a78bfa', '#34d399', '#fbbf24']
const SCENE_SECONDS = 10

function BigStat({ label, value, accent = '#6ee7ff' }) {
  return (
    <div className="flex flex-col items-center justify-center">
      <div className="text-[7vw] font-bold leading-none" style={{ color: accent }}>{value}</div>
      <div className="text-2xl uppercase tracking-widest text-neutral-400 mt-4">{label}</div>
    </div>
  )
}

function OverviewScene({ occupancy, totals }) {
  return (
    <div className="grid grid-cols-2 gap-12 w-full max-w-6xl">
      <BigStat label="Visitors today" value={totals.passersby} accent="#6ee7ff" />
      <BigStat label="On the floor now" value={occupancy.current_count} accent="#34d399" />
      <BigStat label="Stopped by" value={totals.stoppers} accent="#a78bfa" />
      <BigStat label="Capture rate" value={`${Math.round((totals.capture_rate || 0) * 100)}%`} accent="#fbbf24" />
    </div>
  )
}

function TrafficScene({ hourly, demographics }) {
  const genderData = Object.entries(demographics.gender_split || {}).map(([name, value]) => ({ name, value }))
  return (
    <div className="w-full max-w-6xl grid grid-cols-3 gap-8 items-center">
      <div className="col-span-2 h-[50vh]">
        <div className="text-2xl uppercase tracking-widest text-neutral-400 mb-4">Today's traffic</div>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={hourly}>
            <XAxis dataKey="hour" stroke="#888" fontSize={18} />
            <YAxis stroke="#888" fontSize={18} allowDecimals={false} />
            <Tooltip contentStyle={{ background: '#171717', border: '1px solid #333' }} />
            <Bar dataKey="passersby" fill="#6ee7ff" radius={[6, 6, 0, 0]} />
            <Bar dataKey="stoppers" fill="#a78bfa" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="h-[50vh] flex flex-col items-center justify-center min-w-0">
        <div className="text-2xl uppercase tracking-widest text-neutral-400 mb-4">Who's stopping by</div>
        {genderData.length ? (
          <PieChart width={320} height={320}>
            <Pie data={genderData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={70} outerRadius={130}>
              {genderData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Pie>
            <Tooltip contentStyle={{ background: '#171717', border: '1px solid #333' }} />
          </PieChart>
        ) : (
          <div className="text-neutral-500 text-xl">No data yet today</div>
        )}
      </div>
    </div>
  )
}

export default function Kiosk() {
  const { live } = useLiveData()
  const [hourly, setHourly] = useState([])
  const [demographics, setDemographics] = useState({ gender_split: {} })
  const [scene, setScene] = useState(0)

  useEffect(() => {
    const load = () => {
      fetchJSON('/traffic/hourly').then(setHourly).catch(() => {})
      fetchJSON('/demographics/today').then(setDemographics).catch(() => {})
    }
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const t = setInterval(() => setScene((s) => (s + 1) % 2), SCENE_SECONDS * 1000)
    return () => clearInterval(t)
  }, [])

  const occupancy = live?.occupancy ?? { current_count: 0 }
  const totals = live?.totals ?? { passersby: 0, stoppers: 0, capture_rate: 0 }

  return (
    <div className="h-screen w-screen flex flex-col items-center justify-center bg-black overflow-hidden">
      <div className="absolute top-10 left-1/2 -translate-x-1/2 text-4xl font-bold tracking-tight">
        Live Booth Activity
      </div>
      {scene === 0
        ? <OverviewScene occupancy={occupancy} totals={totals} />
        : <TrafficScene hourly={hourly} demographics={demographics} />}
      <div className="absolute bottom-10 flex gap-3">
        {[0, 1].map((i) => (
          <div key={i} className={`h-2 w-2 rounded-full ${i === scene ? 'bg-cyan-400' : 'bg-neutral-700'}`} />
        ))}
      </div>
    </div>
  )
}
