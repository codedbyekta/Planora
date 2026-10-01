import { useEffect, useState } from 'react'
import api from '../services/api'

function startOfDay(date) {
  const d = new Date(date)
  d.setHours(0, 0, 0, 0)
  return d
}

export default function Calendar() {
  const [tasks, setTasks] = useState([])

  useEffect(() => {
    api.get('/tasks').then((res) => setTasks(res.data))
  }, [])

  const today = startOfDay(new Date())
  const tomorrow = new Date(today)
  tomorrow.setDate(tomorrow.getDate() + 1)

  const withDeadline = tasks.filter((t) => t.deadline && !t.completed)

  const overdue = withDeadline.filter((t) => startOfDay(t.deadline) < today)
  const dueToday = withDeadline.filter((t) => startOfDay(t.deadline).getTime() === today.getTime())
  const upcoming = withDeadline
    .filter((t) => startOfDay(t.deadline) > today)
    .sort((a, b) => new Date(a.deadline) - new Date(b.deadline))

  const noDeadline = tasks.filter((t) => !t.deadline && !t.completed)

  return (
    <div>
      <h2 className="mb-6 font-display text-2xl font-semibold text-ink">Calendar</h2>

      <div className="flex flex-col gap-6">
        <TaskGroup title="Overdue" tasks={overdue} accent="danger" />
        <TaskGroup title="Due today" tasks={dueToday} accent="focus" />
        <TaskGroup title="Upcoming" tasks={upcoming} accent="primary" />
        {noDeadline.length > 0 && <TaskGroup title="No deadline set" tasks={noDeadline} accent="ink" />}
      </div>
    </div>
  )
}

function TaskGroup({ title, tasks, accent }) {
  const accentClasses = {
    danger: 'border-l-danger',
    focus: 'border-l-focus',
    primary: 'border-l-primary',
    ink: 'border-l-ink/20',
  }

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-ink/70">
        {title} <span className="text-ink/40">({tasks.length})</span>
      </h3>
      {tasks.length === 0 ? (
        <p className="text-sm text-ink/40">Nothing here.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {tasks.map((t) => (
            <li
              key={t.id}
              className={`rounded-lg border border-border ${accentClasses[accent]} border-l-4 bg-card p-3`}
            >
              <p className="text-sm font-medium text-ink">{t.title}</p>
              <p className="text-xs text-ink/50">
                {t.category} · {t.priority}
                {t.deadline ? ` · ${new Date(t.deadline).toLocaleString()}` : ''}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
