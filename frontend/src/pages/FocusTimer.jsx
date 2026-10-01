import { useEffect, useState } from 'react'
import api from '../services/api'
import { useTimer } from '../context/TimerContext'

const GOAL_OPTIONS = [
  { value: 'achieved', label: 'Yes, fully' },
  { value: 'partial', label: 'Partially' },
  { value: 'not_achieved', label: 'No' },
]

const INTERRUPTION_REASONS = [
  { value: 'urgent_task', label: 'An urgent task came up' },
  {
    value: 'external_interruption',
    label: 'Someone/something interrupted me',
  },
  { value: 'personal', label: 'Personal reason' },
  { value: 'other', label: 'Other' },
]

function formatTime(totalSeconds) {
  const safeSeconds = Math.max(0, totalSeconds)
  const minutes = String(Math.floor(safeSeconds / 60)).padStart(2, '0')
  const seconds = String(safeSeconds % 60).padStart(2, '0')
  return `${minutes}:${seconds}`
}

export default function FocusTimer() {
  const {
    phase,
    session,
    remainingSeconds,
    totalSeconds,
    isIdleNow,
    error,
    setError,
    handleStart,
    handlePause,
    handleResume,
    handleComplete,
    handleInterrupt,
    startNewSession,
  } = useTimer()

  const [tasks, setTasks] = useState([])
  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [interruptReason, setInterruptReason] = useState('urgent_task')
  const [result, setResult] = useState(null)

  const [feedback, setFeedback] = useState({
    focus_rating: 4,
    engagement_rating: 4,
    goal_status: 'achieved',
    idle_reclassified: false,
  })

  useEffect(() => {
    api
      .get('/tasks')
      .then((res) => {
        setTasks(res.data.filter((task) => !task.completed))
      })
      .catch(() => {
        setError('Could not load tasks.')
      })
  }, [setError])

  async function startSession() {
    setError('')
    setResult(null)

    const task = tasks.find(
      (item) => String(item.id) === String(selectedTaskId)
    )

    const durationMinutes =
      task?.remaining_duration ??
      task?.estimated_duration ??
      25

    await handleStart({
      taskId: selectedTaskId || null,
      durationMinutes,
    })
  }

  async function interruptSession() {
    await handleInterrupt(interruptReason)
  }

  async function submitFeedback(event) {
    event.preventDefault()
    setError('')

    try {
      const res = await api.post(
        `/sessions/${session.id}/feedback`,
        feedback
      )

      setResult(res.data)

      const tasksRes = await api.get('/tasks')
      setTasks(tasksRes.data.filter((task) => !task.completed))

      // The timer is no longer active after feedback is submitted.
      // Keep the session result visible until the user starts another.
    } catch (err) {
      setError(
        err.response?.data?.detail || 'Could not submit feedback.'
      )
    }
  }

  function resetAndStartAgain() {
    setFeedback({
      focus_rating: 4,
      engagement_rating: 4,
      goal_status: 'achieved',
      idle_reclassified: false,
    })
    setInterruptReason('urgent_task')
    setResult(null)
    setSelectedTaskId('')
    startNewSession()
  }

  const displayPhase = result ? 'done' : phase

  const statusBanner = {
    idle: null,

    running: isIdleNow
      ? {
          text: 'Idle detected — reading or thinking is okay too.',
          tone: 'bg-focus-light text-focus',
        }
      : {
          text: 'Actively working',
          tone: 'bg-success-light text-success',
        },

    paused: {
      text: 'Paused',
      tone: 'bg-ink/5 text-ink/60',
    },

    awaiting_feedback: {
      text: session?.interrupted
        ? 'Interrupted — tell us what happened'
        : 'Session ended — how did it go?',
      tone: session?.interrupted
        ? 'bg-danger-light text-danger'
        : 'bg-primary-light text-primary',
    },

    done: {
      text:
        result?.validation_status === 'valid'
          ? 'Session saved'
          : 'Session too short to score',
      tone:
        result?.validation_status === 'valid'
          ? 'bg-success-light text-success'
          : 'bg-ink/5 text-ink/60',
    },
  }[displayPhase]

  const circumference = 2 * Math.PI * 90

  const progress =
    totalSeconds > 0
      ? Math.max(
          0,
          Math.min(1, remainingSeconds / totalSeconds)
        )
      : 0

  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-6 py-10">
      <div>
        <h2 className="text-center font-display text-xl font-semibold text-ink">
          Focus Session
        </h2>

        <p className="text-center text-sm text-ink/50">
          Start, pause, or interrupt — your remaining time updates
          automatically.
        </p>
      </div>

      {error && (
        <div className="w-full rounded-lg bg-danger-light px-4 py-2 text-center text-sm text-danger">
          {error}
        </div>
      )}

      {phase === 'idle' && (
        <select
          value={selectedTaskId}
          onChange={(event) => setSelectedTaskId(event.target.value)}
          className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm"
        >
          <option value="">No task selected</option>

          {tasks.map((task) => (
            <option key={task.id} value={task.id}>
              {task.title} (
              {task.remaining_duration ??
                task.estimated_duration ??
                25}{' '}
              min)
            </option>
          ))}
        </select>
      )}

      {displayPhase !== 'idle' && displayPhase !== 'done' && (
        <>
          <div className="relative flex h-56 w-56 items-center justify-center">
            <svg
              className="h-56 w-56 -rotate-90"
              viewBox="0 0 200 200"
            >
              <circle
                cx="100"
                cy="100"
                r="90"
                fill="none"
                stroke="#E4E6F0"
                strokeWidth="12"
              />

              <circle
                cx="100"
                cy="100"
                r="90"
                fill="none"
                stroke={
                  phase === 'paused'
                    ? '#9CA3AF'
                    : isIdleNow
                      ? '#F59E0B'
                      : '#10B981'
                }
                strokeWidth="12"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={circumference * (1 - progress)}
                style={{ transition: 'stroke-dashoffset 1s linear' }}
              />
            </svg>

            <div className="absolute font-display text-4xl font-semibold text-ink">
              {formatTime(remainingSeconds)}
            </div>
          </div>

          {statusBanner && (
            <div
              className={`w-full rounded-lg px-4 py-2 text-center text-sm font-medium ${statusBanner.tone}`}
            >
              {statusBanner.text}
            </div>
          )}
        </>
      )}

      {phase === 'running' && (
        <div className="flex w-full flex-col items-center gap-3">
          <div className="flex flex-wrap justify-center gap-3">
            <button
              onClick={handlePause}
              className="rounded-lg bg-primary px-5 py-2 text-sm font-medium text-white hover:bg-primary-dark"
            >
              Pause
            </button>

            <button
              onClick={() => handleComplete(false)}
              className="rounded-lg border border-border px-5 py-2 text-sm font-medium text-ink/70 hover:bg-surface"
            >
              Complete
            </button>

            <button
              onClick={() => handleComplete(true)}
              className="rounded-lg bg-success px-5 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              Complete &amp; mark task done
            </button>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={interruptReason}
              onChange={(event) =>
                setInterruptReason(event.target.value)
              }
              className="rounded-lg border border-border bg-card px-2 py-1.5 text-xs"
            >
              {INTERRUPTION_REASONS.map((reason) => (
                <option key={reason.value} value={reason.value}>
                  {reason.label}
                </option>
              ))}
            </select>

            <button
              onClick={interruptSession}
              className="rounded-lg border border-danger/30 px-4 py-1.5 text-xs font-medium text-danger hover:bg-danger-light"
            >
              Interrupt
            </button>
          </div>
        </div>
      )}

      {phase === 'paused' && (
        <div className="flex w-full flex-col items-center gap-3">
          <div className="flex flex-wrap justify-center gap-3">
            <button
              onClick={handleResume}
              className="rounded-lg bg-primary px-5 py-2 text-sm font-medium text-white hover:bg-primary-dark"
            >
              Resume
            </button>

            <button
              onClick={() => handleComplete(false)}
              className="rounded-lg border border-border px-5 py-2 text-sm font-medium text-ink/70 hover:bg-surface"
            >
              Complete
            </button>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={interruptReason}
              onChange={(event) =>
                setInterruptReason(event.target.value)
              }
              className="rounded-lg border border-border bg-card px-2 py-1.5 text-xs"
            >
              {INTERRUPTION_REASONS.map((reason) => (
                <option key={reason.value} value={reason.value}>
                  {reason.label}
                </option>
              ))}
            </select>

            <button
              onClick={interruptSession}
              className="rounded-lg border border-danger/30 px-4 py-1.5 text-xs font-medium text-danger hover:bg-danger-light"
            >
              Interrupt
            </button>
          </div>
        </div>
      )}

      {phase === 'idle' && (
        <button
          onClick={startSession}
          className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-white hover:bg-primary-dark"
        >
          Start session
        </button>
      )}

      {phase === 'awaiting_feedback' && !result && (
        <form
          onSubmit={submitFeedback}
          className="w-full rounded-xl border border-border bg-card p-4"
        >
          {session?.interrupted && (
            <div className="mb-3 rounded-lg bg-danger-light px-3 py-2 text-xs text-danger">
              Interrupted:{' '}
              {INTERRUPTION_REASONS.find(
                (reason) =>
                  reason.value === session.interruption_reason
              )?.label || session.interruption_reason}
            </div>
          )}

          <label className="mb-1 block text-xs font-medium text-ink/60">
            How focused did you feel? (1 = not at all, 5 = deep flow)
          </label>

          <div className="mb-3 flex gap-2">
            {[1, 2, 3, 4, 5].map((number) => (
              <button
                type="button"
                key={number}
                onClick={() =>
                  setFeedback((previous) => ({
                    ...previous,
                    focus_rating: number,
                  }))
                }
                className={`h-9 w-9 rounded-lg text-sm font-medium ${
                  feedback.focus_rating === number
                    ? 'bg-primary text-white'
                    : 'bg-surface text-ink/60'
                }`}
              >
                {number}
              </button>
            ))}
          </div>

          <label className="mb-1 block text-xs font-medium text-ink/60">
            How engaging was the work? (1 = boring, 5 = absorbing)
          </label>

          <div className="mb-3 flex gap-2">
            {[1, 2, 3, 4, 5].map((number) => (
              <button
                type="button"
                key={number}
                onClick={() =>
                  setFeedback((previous) => ({
                    ...previous,
                    engagement_rating: number,
                  }))
                }
                className={`h-9 w-9 rounded-lg text-sm font-medium ${
                  feedback.engagement_rating === number
                    ? 'bg-primary text-white'
                    : 'bg-surface text-ink/60'
                }`}
              >
                {number}
              </button>
            ))}
          </div>

          <label className="mb-1 block text-xs font-medium text-ink/60">
            Did you achieve your goal for this session?
          </label>

          <div className="mb-3 flex flex-wrap gap-2">
            {GOAL_OPTIONS.map((goal) => (
              <button
                type="button"
                key={goal.value}
                onClick={() =>
                  setFeedback((previous) => ({
                    ...previous,
                    goal_status: goal.value,
                  }))
                }
                className={`rounded-lg px-3 py-2 text-xs font-medium ${
                  feedback.goal_status === goal.value
                    ? 'bg-primary text-white'
                    : 'bg-surface text-ink/60'
                }`}
              >
                {goal.label}
              </button>
            ))}
          </div>

          {session?.idle_duration > 0 && (
            <label className="mb-3 flex items-start gap-2 rounded-lg bg-focus-light px-3 py-2 text-xs text-ink/80">
              <input
                type="checkbox"
                checked={feedback.idle_reclassified}
                onChange={(event) =>
                  setFeedback((previous) => ({
                    ...previous,
                    idle_reclassified: event.target.checked,
                  }))
                }
              />

              <span>
                We detected {session.idle_duration} min of inactivity.
                Check this if you were actually doing focused work,
                such as reading, thinking, or planning.
              </span>
            </label>
          )}

          <button
            type="submit"
            className="w-full rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-dark"
          >
            Submit feedback
          </button>
        </form>
      )}

      {displayPhase === 'done' && result && (
        <div className="w-full rounded-xl border border-border bg-card p-5 text-center">
          <div
            className={`mb-3 inline-block rounded-full px-3 py-1 text-xs font-medium ${statusBanner?.tone || ''}`}
          >
            {statusBanner?.text}
          </div>

          {result.focus_score != null ? (
            <p className="font-display text-3xl font-semibold text-ink">
              {result.focus_score}
              <span className="text-base text-ink/40">/100</span>
            </p>
          ) : (
            <p className="text-sm text-ink/60">
              This session was too short to count toward your Focus
              Score history.
            </p>
          )}

          <p className="mt-1 text-xs text-ink/50">
            {result.duration_minutes} min ·{' '}
            {result.interrupted ? 'interrupted' : 'completed'}
          </p>

          <button
            onClick={resetAndStartAgain}
            className="mt-4 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-white hover:bg-primary-dark"
          >
            Start another session
          </button>
        </div>
      )}
    </div>
  )
}