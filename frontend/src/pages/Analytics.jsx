import { useEffect, useState } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
  Cell,
} from 'recharts'
import api from '../services/api'

const PIE_COLORS = ['#10B981', '#E4E6F0']

export default function Analytics() {
  const [data, setData] = useState(null)

  useEffect(() => {
    api.get('/analytics').then((res) => setData(res.data))
  }, [])

  if (!data) {
    return <p className="text-sm text-ink/50">Loading analytics…</p>
  }

  if (data.total_sessions === 0) {
    return (
      <div>
        <h2 className="mb-4 font-display text-2xl font-semibold text-ink">Analytics</h2>
        <div className="rounded-xl border border-border bg-card p-6 text-sm text-ink/60">
          No productivity data yet. Complete a few focus sessions to unlock your analytics.
        </div>
      </div>
    )
  }

  const pieData = [
    { name: 'Completed', value: data.completed_vs_pending.completed },
    { name: 'Pending', value: data.completed_vs_pending.pending },
  ]

  return (
    <div className="flex flex-col gap-8">
      <h2 className="font-display text-2xl font-semibold text-ink">Analytics</h2>

      <ChartCard title={`Daily focus time (14 days) — ${data.weekly_focus_minutes} min this week`}>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data.daily_focus_time}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E4E6F0" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d) => d.slice(5)} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="minutes" fill="#4F46E5" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ChartCard title="Focus score trend">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data.focus_score_trend}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E4E6F0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d) => d.slice(5)} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey="avg_score" stroke="#F59E0B" strokeWidth={2} connectNulls dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Completed vs pending tasks">
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80}>
                {pieData.map((entry, i) => (
                  <Cell key={entry.name} fill={PIE_COLORS[i]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Most productive hours">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data.most_productive_hours}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E4E6F0" />
              <XAxis dataKey="hour" tick={{ fontSize: 11 }} tickFormatter={(h) => `${h}:00`} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="avg_score" fill="#4F46E5" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Productivity by day of week">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data.productivity_by_day}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E4E6F0" />
              <XAxis dataKey="day" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(0, 3)} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="avg_score" fill="#10B981" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  )
}

function ChartCard({ title, children }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h3 className="mb-3 text-sm font-semibold text-ink">{title}</h3>
      {children}
    </div>
  )
}
