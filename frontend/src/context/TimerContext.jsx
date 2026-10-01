import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react'
import api from '../services/api'

const TimerContext = createContext(null)

const PING_INTERVAL_MS = 20000
const IDLE_THRESHOLD_MS = 8000

export function TimerProvider({ children }) {
  const [phase, setPhase] = useState('idle')
  const [session, setSession] = useState(null)
  const [remainingSeconds, setRemainingSeconds] = useState(0)
  const [totalSeconds, setTotalSeconds] = useState(0)
  const [isIdleNow, setIsIdleNow] = useState(false)
  const [error, setError] = useState('')

  const endTimeRef = useRef(null)
  const lastActivityAt = useRef(Date.now())
  const activeSecondsRef = useRef(0)
  const idleSecondsRef = useRef(0)
  const completingRef = useRef(false)

  // Track activity while a session is running.
  const markActivity = useCallback(() => {
    lastActivityAt.current = Date.now()
  }, [])

  useEffect(() => {
    if (phase !== 'running') return

    const events = ['mousemove', 'keydown', 'click', 'scroll']
    events.forEach((event) =>
      window.addEventListener(event, markActivity)
    )

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        markActivity()
      }
    }

    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      events.forEach((event) =>
        window.removeEventListener(event, markActivity)
      )
      document.removeEventListener(
        'visibilitychange',
        handleVisibility
      )
    }
  }, [phase, markActivity])

  // Timestamp-based countdown survives route changes.
  useEffect(() => {
    if (phase !== 'running') return

    const tick = () => {
      if (!endTimeRef.current) return

      const secondsLeft = Math.max(
        0,
        Math.ceil((endTimeRef.current - Date.now()) / 1000)
      )

      setRemainingSeconds(secondsLeft)

      const idle = Date.now() - lastActivityAt.current > IDLE_THRESHOLD_MS
      setIsIdleNow(idle)

      if (idle) {
        idleSecondsRef.current += 1
      } else {
        activeSecondsRef.current += 1
      }
    }

    tick()
    const interval = setInterval(tick, 1000)

    return () => clearInterval(interval)
  }, [phase])

  // Send aggregated activity to the backend.
  const sendPing = useCallback(async () => {
    if (!session) return

    const active_seconds = activeSecondsRef.current
    const idle_seconds = idleSecondsRef.current

    if (active_seconds === 0 && idle_seconds === 0) return

    activeSecondsRef.current = 0
    idleSecondsRef.current = 0

    try {
      const res = await api.post(
        `/sessions/${session.id}/activity`,
        { active_seconds, idle_seconds }
      )
      setSession(res.data)
    } catch {
      // The session may already have ended.
    }
  }, [session])

  useEffect(() => {
    if (phase !== 'running') return

    const interval = setInterval(() => {
      sendPing()
    }, PING_INTERVAL_MS)

    return () => clearInterval(interval)
  }, [phase, sendPing])

  const handleStart = useCallback(
    async ({ taskId = null, durationMinutes = 25 } = {}) => {
      setError('')

      try {
        const res = await api.post('/sessions/start', {
          task_id: taskId || null,
        })

        const seconds = Math.max(
          1,
          Math.round(Number(durationMinutes) * 60)
        )

        setSession(res.data)
        setTotalSeconds(seconds)
        setRemainingSeconds(seconds)

        endTimeRef.current = Date.now() + seconds * 1000
        activeSecondsRef.current = 0
        idleSecondsRef.current = 0
        lastActivityAt.current = Date.now()
        completingRef.current = false

        setIsIdleNow(false)
        setPhase('running')
      } catch (err) {
        setError(
          err.response?.data?.detail || 'Could not start the session.'
        )
      }
    },
    []
  )

  const handlePause = useCallback(async () => {
    if (!session || phase !== 'running') return

    try {
      await sendPing()
      await api.post(`/sessions/${session.id}/pause`)

      const secondsLeft = endTimeRef.current
        ? Math.max(
            0,
            Math.ceil((endTimeRef.current - Date.now()) / 1000)
          )
        : remainingSeconds

      endTimeRef.current = null
      setRemainingSeconds(secondsLeft)
      setPhase('paused')
      setIsIdleNow(false)
    } catch (err) {
      setError(
        err.response?.data?.detail || 'Could not pause the session.'
      )
    }
  }, [session, phase, sendPing, remainingSeconds])

  const handleResume = useCallback(async () => {
    if (!session || phase !== 'paused') return

    try {
      await api.post(`/sessions/${session.id}/resume`)

      endTimeRef.current =
        Date.now() + remainingSeconds * 1000

      lastActivityAt.current = Date.now()
      setIsIdleNow(false)
      setPhase('running')
    } catch (err) {
      setError(
        err.response?.data?.detail || 'Could not resume the session.'
      )
    }
  }, [session, phase, remainingSeconds])

  const handleComplete = useCallback(
    async (markTaskCompleted = false) => {
      if (!session || completingRef.current) return

      completingRef.current = true

      try {
        await sendPing()

        const res = await api.post(
          `/sessions/${session.id}/complete`,
          { completed_task: markTaskCompleted }
        )

        endTimeRef.current = null
        setRemainingSeconds(0)
        setSession(res.data)
        setPhase('awaiting_feedback')
        setIsIdleNow(false)
      } catch (err) {
        setError(
          err.response?.data?.detail || 'Could not complete the session.'
        )
      } finally {
        completingRef.current = false
      }
    },
    [session, sendPing]
  )

  // Automatically complete when the countdown reaches zero.
  useEffect(() => {
    if (
      phase === 'running' &&
      remainingSeconds === 0 &&
      session &&
      !completingRef.current
    ) {
      handleComplete(false)
    }
  }, [phase, remainingSeconds, session, handleComplete])

  const handleInterrupt = useCallback(
    async (interruptReason) => {
      if (!session || completingRef.current) return

      completingRef.current = true

      try {
        await sendPing()

        const res = await api.post(
          `/sessions/${session.id}/interrupt`,
          { interruption_reason: interruptReason }
        )

        endTimeRef.current = null
        setSession(res.data)
        setPhase('awaiting_feedback')
        setIsIdleNow(false)
      } catch (err) {
        setError(
          err.response?.data?.detail || 'Could not interrupt the session.'
        )
      } finally {
        completingRef.current = false
      }
    },
    [session, sendPing]
  )

  const startNewSession = useCallback(() => {
    endTimeRef.current = null
    activeSecondsRef.current = 0
    idleSecondsRef.current = 0
    completingRef.current = false

    setPhase('idle')
    setSession(null)
    setRemainingSeconds(0)
    setTotalSeconds(0)
    setIsIdleNow(false)
    setError('')
  }, [])

  return (
    <TimerContext.Provider
      value={{
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
      }}
    >
      {children}
    </TimerContext.Provider>
  )
}

export function useTimer() {
  const context = useContext(TimerContext)

  if (!context) {
    throw new Error('useTimer must be used inside TimerProvider')
  }

  return context
}