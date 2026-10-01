import { useEffect, useState } from 'react'
import api from '../services/api'

function formatHour(h) {
  if (h == null) return ''
  const period = h < 12 ? 'AM' : 'PM'
  let display = h % 12
  if (display === 0) display = 12
  return `${display} ${period}`
}

export default function Recommendations() {
  const [rec, setRec] = useState(null)
  const [predictions, setPredictions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api.get('/recommendations'), api.get('/predictions')])
      .then(([recRes, predRes]) => {
        setRec(recRes.data)
        setPredictions(predRes.data)
      })
      .catch(() => setError('Could not load your recommendations right now.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <p className="text-sm text-ink/50">Loading your recommendations…</p>
  if (error) return <div className="rounded-lg bg-danger-light px-4 py-3 text-sm text-danger">{error}</div>

  const sortedPredictions = [...predictions].sort((a, b) => new Date(a.window_start) - new Date(b.window_start))
  const maxScore = Math.max(1, ...sortedPredictions.map((p) => p.predicted_focus_score))

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="font-display text-2xl font-semibold text-ink">Recommendations</h2>
        <p className="text-sm text-ink/50">When you tend to focus best, based on your validated sessions</p>
      </div>

      {rec && (
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center justify-between">
            <p className="font-display text-lg font-semibold text-ink">
              {rec.recommended_start_hour != null
                ? `${formatHour(rec.recommended_start_hour)} – ${formatHour(rec.recommended_end_hour)}`
                : 'Not enough data yet'}
            </p>
            <span
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                rec.source === 'ml_model' ? 'bg-primary-light text-primary' : 'bg-ink/5 text-ink/60'
              }`}
            >
              {rec.source === 'ml_model' ? 'Personalized model' : 'Historical average'}
            </span>
          </div>
          <p className="mt-2 text-sm text-ink/70">{rec.reason}</p>
        </div>
      )}

      {sortedPredictions.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="mb-4 font-display text-sm font-semibold text-ink">Predicted focus by time window</h3>
          <div className="flex flex-col gap-3">
            {sortedPredictions.map((p, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="w-28 shrink-0 text-xs text-ink/60">
                  {new Date(p.window_start).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                  {' – '}
                  {new Date(p.window_end).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                </div>
                <div className="h-3 flex-1 overflow-hidden rounded-full bg-surface">
                  <div
                    className={`h-full rounded-full ${p.source === 'ml_model' ? 'bg-primary' : 'bg-focus'}`}
                    style={{ width: `${(p.predicted_focus_score / maxScore) * 100}%` }}
                  />
                </div>
                <div className="w-12 shrink-0 text-right text-xs font-medium text-ink/70">
                  {p.predicted_focus_score}
                </div>
              </div>
            ))}
          </div>
          <p className="mt-4 text-xs text-ink/40">
            Bars show relative predicted Focus Score (0–100) for each window you've historically logged sessions in.
          </p>
        </div>
      )}
    </div>
  )
}
