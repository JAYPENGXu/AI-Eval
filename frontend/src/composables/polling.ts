import { getSessionSignal, isAbortError, shouldIgnoreRequestError } from '../api/authSession'

export { isAbortError, shouldIgnoreRequestError }

export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}

export async function sleep(ms: number, signal?: AbortSignal | null): Promise<void> {
  const activeSignal = signal ?? getSessionSignal()
  if (activeSignal.aborted) {
    throw new DOMException('Aborted', 'AbortError')
  }
  await new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      activeSignal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      window.clearTimeout(timer)
      activeSignal.removeEventListener('abort', onAbort)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    activeSignal.addEventListener('abort', onAbort, { once: true })
  })
}
