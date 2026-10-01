import { useEffect, useState } from 'react'
import api from '../services/api'

const CATEGORIES = ['Study', 'Coding', 'Work', 'Personal']
const PRIORITIES = ['low', 'medium', 'high', 'urgent']
const DIFFICULTIES = ['easy', 'medium', 'hard']

const EMPTY_FORM = {
  title: '',
  description: '',
  deadline: '',
  priority: 'medium',
  difficulty: 'medium',
  estimated_duration: 30,
  category: 'Personal',
}

const PRIORITY_STYLES = {
  low: 'bg-ink/5 text-ink/60',
  medium: 'bg-primary-light text-primary',
  high: 'bg-focus-light text-focus',
  urgent: 'bg-danger-light text-danger',
}

const STATUS_STYLES = {
  pending: 'bg-ink/5 text-ink/60',
  in_progress: 'bg-focus-light text-focus',
  completed: 'bg-success-light text-success',
  blocked: 'bg-danger-light text-danger',
}

export default function Tasks() {
  const [tasks, setTasks] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [suggestions, setSuggestions] = useState({}) // taskId -> suggestion
  const [error, setError] = useState('')
  const [form, setForm] = useState(EMPTY_FORM)

  function loadTasks() {
    api.get('/tasks').then((res) => setTasks(res.data)).catch(() => setError('Could not load tasks.'))
  }

  useEffect(loadTasks, [])

  function openCreateForm() {
    setForm(EMPTY_FORM)
    setEditingId(null)
    setShowForm(true)
  }

  function openEditForm(task) {
    setForm({
      title: task.title,
      description: task.description || '',
      deadline: task.deadline ? task.deadline.slice(0, 16) : '',
      priority: task.priority,
      difficulty: task.difficulty,
      estimated_duration: task.estimated_duration,
      category: task.category,
    })
    setEditingId(task.id)
    setShowForm(true)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    const payload = {
      ...form,
      estimated_duration: Number(form.estimated_duration),
      deadline: form.deadline ? new Date(form.deadline).toISOString() : null,
    }
    try {
      if (editingId) {
        await api.put(`/tasks/${editingId}`, payload)
      } else {
        await api.post('/tasks', payload)
      }
      setForm(EMPTY_FORM)
      setEditingId(null)
      setShowForm(false)
      loadTasks()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save this task.')
    }
  }

  async function toggleComplete(task) {
    await api.put(`/tasks/${task.id}`, { completed: !task.completed })
    loadTasks()
  }

  async function deleteTask(id) {
    await api.delete(`/tasks/${id}`)
    loadTasks()
  }

  async function fetchSuggestion(taskId) {
    const res = await api.get(`/tasks/${taskId}/suggested-time`)
    setSuggestions((prev) => ({ ...prev, [taskId]: res.data }))
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h2 className="font-display text-2xl font-semibold text-ink">Tasks</h2>
        <button
          onClick={() => (showForm ? setShowForm(false) : openCreateForm())}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-dark"
        >
          {showForm ? 'Cancel' : '+ New Task'}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-danger-light px-4 py-2 text-sm text-danger">{error}</div>
      )}

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="mb-6 grid grid-cols-1 gap-3 rounded-xl border border-border bg-card p-4 sm:grid-cols-2"
        >
          <input
            required
            placeholder="Task title"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className="rounded-lg border border-border px-3 py-2 text-sm sm:col-span-2"
          />
          <textarea
            placeholder="Description (optional)"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            className="rounded-lg border border-border px-3 py-2 text-sm sm:col-span-2"
          />
          <label className="flex flex-col gap-1 text-xs text-ink/50">
            Deadline
            <input
              type="datetime-local"
              value={form.deadline}
              onChange={(e) => setForm({ ...form, deadline: e.target.value })}
              className="rounded-lg border border-border px-3 py-2 text-sm text-ink"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink/50">
            Estimated duration (minutes)
            <input
              type="number"
              min="5"
              value={form.estimated_duration}
              onChange={(e) => setForm({ ...form, estimated_duration: e.target.value })}
              className="rounded-lg border border-border px-3 py-2 text-sm text-ink"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink/50">
            Priority
            <select
              value={form.priority}
              onChange={(e) => setForm({ ...form, priority: e.target.value })}
              className="rounded-lg border border-border px-3 py-2 text-sm text-ink"
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink/50">
            Difficulty
            <select
              value={form.difficulty}
              onChange={(e) => setForm({ ...form, difficulty: e.target.value })}
              className="rounded-lg border border-border px-3 py-2 text-sm text-ink"
            >
              {DIFFICULTIES.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-ink/50">
            Category
            <select
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
              className="rounded-lg border border-border px-3 py-2 text-sm text-ink"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-dark sm:col-span-2"
          >
            {editingId ? 'Save changes' : 'Add task'}
          </button>
        </form>
      )}

      {tasks.length === 0 ? (
        <p className="text-sm text-ink/50">No tasks yet. Create your first one above.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {tasks.map((t) => (
            <li key={t.id} className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    checked={t.completed}
                    onChange={() => toggleComplete(t)}
                    className="mt-1"
                  />
                  <div>
                    <p className={`text-sm font-medium ${t.completed ? 'text-ink/40 line-through' : 'text-ink'}`}>
                      {t.title}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${PRIORITY_STYLES[t.priority]}`}>
                        {t.priority}
                      </span>
                      <span className="rounded-full bg-ink/5 px-2 py-0.5 text-xs font-medium text-ink/60">
                        {t.difficulty}
                      </span>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[t.status] || 'bg-ink/5 text-ink/60'}`}>
                        {t.status.replace('_', ' ')}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-ink/50">
                      {t.category} · {t.remaining_duration ?? t.estimated_duration}/{t.estimated_duration} min remaining
                      {t.deadline ? ` · due ${new Date(t.deadline).toLocaleString()}` : ''}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  {!t.completed && (
                    <button
                      onClick={() => fetchSuggestion(t.id)}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      Suggest time
                    </button>
                  )}
                  <button
                    onClick={() => openEditForm(t)}
                    className="text-xs font-medium text-ink/60 hover:underline"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => deleteTask(t.id)}
                    className="text-xs font-medium text-danger hover:underline"
                  >
                    Delete
                  </button>
                </div>
              </div>

              {suggestions[t.id] && (
                <div className="rounded-lg bg-focus-light px-3 py-2 text-xs text-ink/80">
                  {suggestions[t.id].suggested_start ? (
                    <>
                      <span className="font-medium">
                        {suggestions[t.id].day_label},{' '}
                        {new Date(suggestions[t.id].suggested_start).toLocaleTimeString([], {
                          hour: 'numeric',
                          minute: '2-digit',
                        })}
                        {' – '}
                        {new Date(suggestions[t.id].suggested_end).toLocaleTimeString([], {
                          hour: 'numeric',
                          minute: '2-digit',
                        })}
                      </span>{' '}
                      — {suggestions[t.id].reason}
                    </>
                  ) : (
                    suggestions[t.id].reason
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
