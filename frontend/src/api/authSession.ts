export class UnauthorizedError extends Error {
  status = 401

  constructor(message = '登录已失效，请重新登录') {
    super(message)
    this.name = 'UnauthorizedError'
  }
}

let sessionController = new AbortController()
let onSessionInvalidated: (() => void) | null = null

export function getSessionSignal(): AbortSignal {
  return sessionController.signal
}

export function setOnSessionInvalidated(handler: (() => void) | null) {
  onSessionInvalidated = handler
}

export function abortActiveRequests() {
  sessionController.abort()
  sessionController = new AbortController()
}

export function invalidateSession() {
  abortActiveRequests()
  onSessionInvalidated?.()
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === 'AbortError'
    : (error as { name?: string })?.name === 'AbortError'
}

export function isUnauthorizedError(error: unknown): boolean {
  return error instanceof UnauthorizedError || (error as { status?: number })?.status === 401
}

export function shouldIgnoreRequestError(error: unknown): boolean {
  return isAbortError(error) || isUnauthorizedError(error)
}

export function mergeSignals(...signals: Array<AbortSignal | undefined | null>): AbortSignal | undefined {
  const active = signals.filter(Boolean) as AbortSignal[]
  if (!active.length) return undefined
  if (active.length === 1) return active[0]
  if (typeof AbortSignal !== 'undefined' && 'any' in AbortSignal && typeof AbortSignal.any === 'function') {
    return AbortSignal.any(active)
  }
  const controller = new AbortController()
  const abort = () => controller.abort()
  for (const signal of active) {
    if (signal.aborted) {
      abort()
      break
    }
    signal.addEventListener('abort', abort, { once: true })
  }
  return controller.signal
}
