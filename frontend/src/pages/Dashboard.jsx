import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'

function formatHour(hour) {
  if (hour === null || hour === undefined) return ''
  const period = hour < 12 ? 'AM' : 'PM'
  let h = hour % 12
  if (h === 0) h = 12
  return `${h} ${period}`
}

function ReminderList({ title, items, accent }) {
  const accentText = { danger: 'text-danger', focus: 'text-focus', primary: 'text-primary' }
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h4 className={`mb-2 text-xs font-semibold ${accentText[accent]}`}>
        {title} ({items.length})
      </h4>
      {items.length === 0 ? (
        <p className="text-xs text-ink/40">Nothing here.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((t) => (
            <li key={t.id} className="text-sm text-ink">
              {t.title}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [rec, setRec] = useState(null)
  const [activeSession, setActiveSession] = useState(null)
  const [schedulePreview, setSchedulePreview] = useState([])

  useEffect(() => {
    api.get('/dashboard').then((res) => setData(res.data))
    api.get('/recommendations').then((res) => setRec(res.data))
    api.get('/sessions').then((res) => {
      const inProgress = res.data.find((s) => !s.end_time)
      setActiveSession(inProgress || null)
    })
    api
      .get('/schedule')
      .then((res) => setSchedulePreview([...(res.data.plan || [])]
        .sort((a, b) => new Date(a.window_start) - new Date(b.window_start))
        .slice(0, 3)))
      .catch(() => {})
  }, [])

  if (!data) {
    return <p className="text-sm text-ink/50">Loading dashboard…</p>
  }

  const cards = [
    { label: 'Total tasks', value: data.total_tasks },
    { label: 'Completed', value: data.completed_tasks },
    { label: 'Pending', value: data.pending_tasks },
    { label: "Today's focus (min)", value: data.todays_focus_minutes },
    { label: "Today's focus score", value: data.todays_focus_score },
  ]

  return (
    <div>
      <h2 className="mb-6 font-display text-2xl font-semibold text-ink">Dashboard</h2>

      <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {cards.map((c) => (
          <div key={c.label} className="rounded-xl border border-border bg-card p-4">
            <p className="text-xs text-ink/50">{c.label}</p>
            <p className="mt-1 font-display text-2xl font-semibold text-ink">{c.value}</p>
          </div>
        ))}
      </div>

      {activeSession && (
        <div className="mb-8 flex items-center justify-between rounded-xl border border-success/30 bg-success-light p-4">
          <div>
            <h3 className="text-sm font-semibold text-ink">Session in progress</h3>
            <p className="text-sm text-ink/70">Started {new Date(activeSession.start_time).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</p>
          </div>
          <Link to="/session" className="rounded-lg bg-success px-4 py-2 text-sm font-medium text-white hover:opacity-90">
            Resume
          </Link>
        </div>
      )}

      {rec && (
        <div className="mb-8 rounded-xl border border-focus/30 bg-focus-light p-4">
          <div className="mb-1 flex items-center gap-2">
            <h3 className="text-sm font-semibold text-ink">Recommended focus time</h3>
            <span className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-ink/50">
              {rec.source === 'ml_model' ? 'AI model' : 'Historical average'}
            </span>
          </div>
          {rec.recommended_start_hour !== null ? (
            <p className="text-sm text-ink/80">
              <span className="font-medium">
                {formatHour(rec.recommended_start_hour)} – {formatHour(rec.recommended_end_hour)}
              </span>{' '}
              — {rec.reason}
            </p>
          ) : (
            <p className="text-sm text-ink/60">{rec.reason}</p>
          )}
        </div>
      )}

      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <ReminderList title="Overdue" items={data.reminders.overdue} accent="danger" />
        <ReminderList title="Due today" items={data.reminders.due_today} accent="focus" />
        <ReminderList title="Due tomorrow" items={data.reminders.due_tomorrow} accent="primary" />
      </div>

      {schedulePreview.length > 0 && (
        <div className="mb-8 rounded-xl border border-border bg-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink">Up next in your schedule</h3>
            <Link to="/schedule" className="text-xs font-medium text-primary hover:underline">View full schedule</Link>
          </div>
          <ul className="flex flex-col gap-2">
            {schedulePreview.map((item, i) => (
              <li key={i} className="flex items-center justify-between text-sm">
                <span className="text-ink">{item.task_title}</span>
                <span className="text-xs text-ink/50">
                  {new Date(item.window_start).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-xl border border-border bg-card p-4">
        <h3 className="mb-3 text-sm font-semibold text-ink">Today's tasks</h3>
        {data.todays_task_list.length === 0 ? (
          <p className="text-sm text-ink/50">No tasks yet. Head to the Tasks page to add one.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {data.todays_task_list.map((t) => (
              <li key={t.id} className="flex items-center justify-between text-sm">
                <span className={t.completed ? 'text-ink/40 line-through' : 'text-ink'}>
                  {t.title}
                </span>
                <span className="rounded-full bg-primary-light px-2 py-0.5 text-xs text-primary">
                  {t.priority}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
