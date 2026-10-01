import { useEffect, useState } from 'react'
import {
  Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { fetchJSON, useLiveData } from './useLiveData'

const COLORS = ['#6ee7ff', '#a78bfa', '#34d399', '#fbbf24', '#f87171']

function Card({ title, children, className = '' }) {
  return (
    <div className={`rounded-xl bg-neutral-900 border border-neutral-800 p-4 min-w-0 ${className}`}>
      <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">{title}</h2>
      {children}
    </div>
  )
}

function AlertBanner({ alerts }) {
  if (!alerts?.length) return null
  return (
    <div className="rounded-xl bg-red-950 border border-red-700 p-3 mb-4 space-y-1">
      {alerts.map((a) => (
        <div key={a.alert_id} className="text-red-300 text-sm">
          <span className="font-semibold uppercase">{a.type.replace('_', ' ')}</span> — {a.detail}
        </div>
      ))}
    </div>
  )
}

function DonutChart({ split }) {
  const data = Object.entries(split || {}).map(([name, value]) => ({ name, value }))
  if (!data.length) return <p className="text-neutral-500 text-sm">No data yet today.</p>
  return (
    <PieChart width={220} height={180} className="mx-auto">
      <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={40} outerRadius={70}>
        {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
      </Pie>
      <Tooltip contentStyle={{ background: '#171717', border: '1px solid #333' }} />
    </PieChart>
  )
}

function bucketDwell(values) {
  const buckets = { '0-10s': 0, '10-30s': 0, '30-60s': 0, '60s+': 0 }
  for (const v of values || []) {
    if (v < 10) buckets['0-10s']++
    else if (v < 30) buckets['10-30s']++
    else if (v < 60) buckets['30-60s']++
    else buckets['60s+']++
  }
  return Object.entries(buckets).map(([name, count]) => ({ name, count }))
}

export default function App() {
  const { live, connected } = useLiveData()
  const [hourly, setHourly] = useState([])
  const [demographics, setDemographics] = useState({ gender_split: {}, age_split: {} })
  const [dwell, setDwell] = useState([])

  useEffect(() => {
    const load = () => {
      fetchJSON('/traffic/hourly').then(setHourly).catch(() => {})
      fetchJSON('/demographics/today').then(setDemographics).catch(() => {})
      fetchJSON('/dwell/distribution').then(setDwell).catch(() => {})
    }
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])

  const occupancy = live?.occupancy ?? { current_count: 0, staff_count: 0 }
  const totals = live?.totals ?? { passersby: 0, stoppers: 0, capture_rate: 0, avg_dwell: 0 }

  return (
    <div className="min-h-screen px-4 py-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">Booth Analytics</h1>
        <div className="flex items-center gap-3">
          <a href="/live" className="text-xs px-2 py-1 rounded-full bg-neutral-800 text-neutral-300 hover:bg-neutral-700">
            live track
          </a>
          <span className={`text-xs px-2 py-1 rounded-full ${connected ? 'bg-emerald-900 text-emerald-300' : 'bg-neutral-800 text-neutral-400'}`}>
            {connected ? 'live' : 'polling'}
          </span>
        </div>
      </div>

      <AlertBanner alerts={live?.active_alerts} />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <Card title="Current occupancy">
          <p className="text-3xl font-bold">{occupancy.current_count}</p>
        </Card>
        <Card title="Staff on floor">
          <p className="text-3xl font-bold">{occupancy.staff_count}</p>
        </Card>
        <Card title="Passersby today">
          <p className="text-3xl font-bold">{totals.passersby}</p>
        </Card>
        <Card title="Capture rate">
          <p className="text-3xl font-bold">{(totals.capture_rate * 100).toFixed(0)}%</p>
        </Card>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Card title="Hourly traffic" className="sm:col-span-2">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={hourly}>
              <XAxis dataKey="hour" stroke="#888" fontSize={12} />
              <YAxis stroke="#888" fontSize={12} />
              <Tooltip contentStyle={{ background: '#171717', border: '1px solid #333' }} />
              <Bar dataKey="passersby" fill="#6ee7ff" radius={[4, 4, 0, 0]} />
              <Bar dataKey="stoppers" fill="#a78bfa" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Gender split">
          <DonutChart split={demographics.gender_split} />
        </Card>
        <Card title="Age split">
          <DonutChart split={demographics.age_split} />
        </Card>

        <Card title="Dwell time distribution" className="sm:col-span-2">
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={bucketDwell(dwell)}>
              <XAxis dataKey="name" stroke="#888" fontSize={12} />
              <YAxis stroke="#888" fontSize={12} allowDecimals={false} />
              <Tooltip contentStyle={{ background: '#171717', border: '1px solid #333' }} />
              <Bar dataKey="count" fill="#34d399" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  )
}
