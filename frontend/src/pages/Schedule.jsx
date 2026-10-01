import { useEffect, useState } from 'react'
import api from '../services/api'

const PRIORITY_STYLES = {
  low: 'bg-ink/5 text-ink/60',
  medium: 'bg-primary-light text-primary',
  high: 'bg-focus-light text-focus',
  urgent: 'bg-danger-light text-danger',
}

export default function Schedule() {
  const [schedule, setSchedule] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get('/schedule')
      .then((res) => setSchedule(res.data))
      .catch(() => setError('Could not load your schedule right now.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <p className="text-sm text-ink/50">Building your schedule…</p>
  if (error) return <div className="rounded-lg bg-danger-light px-4 py-3 text-sm text-danger">{error}</div>

  const plan = [...(schedule?.plan || [])].sort((a, b) => new Date(a.window_start) - new Date(b.window_start))
  const unscheduled = schedule?.unscheduled || []

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="font-display text-2xl font-semibold text-ink">Your Schedule</h2>
        <p className="text-sm text-ink/50">Tasks matched to your predicted focus windows</p>
      </div>

      {plan.length === 0 ? (
        <p className="text-sm text-ink/50">No open tasks to schedule yet — add one from the Tasks page.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {plan.map((item, i) => (
            <li key={i} className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-medium text-ink/50">
                    {new Date(item.window_start).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                    {' – '}
                    {new Date(item.window_end).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                  </p>
                  <p className="mt-0.5 font-medium text-ink">{item.task_title}</p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${PRIORITY_STYLES[item.task_priority] || ''}`}>
                      {item.task_priority}
                    </span>
                    <span className="rounded-full bg-ink/5 px-2 py-0.5 text-xs font-medium text-ink/60">
                      {item.task_difficulty}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        item.source === 'ml_model' ? 'bg-primary-light text-primary' : 'bg-ink/5 text-ink/60'
                      }`}
                    >
                      predicted {item.predicted_focus_score}
                    </span>
                  </div>
                </div>
              </div>
              <p className="mt-2 text-xs text-ink/60">{item.reason}</p>
            </li>
          ))}
        </ul>
      )}

      {unscheduled.length > 0 && (
        <div>
          <h3 className="mb-2 font-display text-sm font-semibold text-ink">Not scheduled</h3>
          <ul className="flex flex-col gap-2">
            {unscheduled.map((u, i) => (
              <li key={i} className="rounded-xl border border-dashed border-border bg-surface p-3">
                <p className="text-sm font-medium text-ink/70">{u.task_title}</p>
                <p className="text-xs text-ink/50">{u.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
