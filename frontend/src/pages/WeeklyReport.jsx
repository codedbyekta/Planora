import { useEffect, useState } from 'react'
import api from '../services/api'

export default function WeeklyReport() {
  const [report, setReport] = useState(null)

  useEffect(() => {
    api.get('/weekly-report').then((res) => setReport(res.data))
  }, [])

  if (!report) {
    return <p className="text-sm text-ink/50">Loading report…</p>
  }

  if (report.this_week.session_count === 0) {
    return (
      <div>
        <h2 className="mb-4 font-display text-2xl font-semibold text-ink">Weekly Report</h2>
        <div className="rounded-xl border border-border bg-card p-6 text-sm text-ink/60">
          {report.insight}
        </div>
      </div>
    )
  }

  const { this_week, last_week, change_vs_last_week_percent } = report

  const cards = [
    { label: 'Focus time', value: `${Math.round((this_week.total_focus_minutes / 60) * 10) / 10}h` },
    { label: 'Tasks completed', value: this_week.tasks_completed },
    { label: 'Avg focus score', value: this_week.average_focus_score },
    { label: 'Best day', value: this_week.best_day ?? '—' },
    {
      label: 'Most productive hour',
      value: this_week.most_productive_hour !== null ? `${this_week.most_productive_hour}:00` : '—',
    },
  ]

  return (
    <div>
      <h2 className="mb-6 font-display text-2xl font-semibold text-ink">Weekly Report</h2>

      <div className="mb-6 rounded-xl border border-primary/30 bg-primary-light p-4">
        <p className="text-sm text-ink/80">{report.insight}</p>
      </div>

      <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {cards.map((c) => (
          <div key={c.label} className="rounded-xl border border-border bg-card p-4">
            <p className="text-xs text-ink/50">{c.label}</p>
            <p className="mt-1 font-display text-xl font-semibold text-ink">{c.value}</p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="mb-3 text-sm font-semibold text-ink">This week vs last week</h3>
        <div className="flex items-center gap-6 text-sm">
          <div>
            <p className="text-ink/50">This week</p>
            <p className="font-display text-lg font-semibold text-ink">
              {Math.round((this_week.total_focus_minutes / 60) * 10) / 10}h
            </p>
          </div>
          <div>
            <p className="text-ink/50">Last week</p>
            <p className="font-display text-lg font-semibold text-ink">
              {Math.round((last_week.total_focus_minutes / 60) * 10) / 10}h
            </p>
          </div>
          {change_vs_last_week_percent !== null && (
            <div>
              <p className="text-ink/50">Change</p>
              <p
                className={`font-display text-lg font-semibold ${
                  change_vs_last_week_percent >= 0 ? 'text-success' : 'text-danger'
                }`}
              >
                {change_vs_last_week_percent >= 0 ? '+' : ''}
                {change_vs_last_week_percent}%
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
