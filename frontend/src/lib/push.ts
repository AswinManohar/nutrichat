import { apiClient, ApiError } from '../api/client'

/** Outcome of an attempt to enable push reminders. */
export type PushResult =
  | 'subscribed' // permission granted, subscription stored
  | 'unsupported' // browser lacks SW/Push/Notification (e.g. iOS Safari web)
  | 'denied' // user blocked notifications
  | 'not-configured' // server has no VAPID key set
  | 'error' // unexpected failure

interface VapidKeyResponse {
  public_key: string
}

/**
 * True when the browser supports the Web Push primitives we need. Notably false
 * on iOS Safari running as a normal tab (it only supports push for installed
 * PWAs), so the onboarding UI hides the reminder toggle in that case.
 */
export function isPushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
}

/** Convert a base64url VAPID key into the Uint8Array the Push API expects. */
function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = window.atob(base64)
  const output = new Uint8Array(raw.length) as Uint8Array<ArrayBuffer>
  for (let i = 0; i < raw.length; i += 1) {
    output[i] = raw.charCodeAt(i)
  }
  return output
}

/**
 * Register the service worker, request notification permission, subscribe to
 * push, and persist the subscription on the backend. Safe to call only after a
 * user gesture (some browsers require it for the permission prompt).
 */
export async function enablePushReminders(): Promise<PushResult> {
  if (!isPushSupported()) return 'unsupported'

  // Fetch the server's VAPID key first — a 404 means push isn't configured, so
  // we bail before prompting the user for permission we can't fulfil.
  let publicKey: string
  try {
    const res = await apiClient.get<VapidKeyResponse>('/push/vapid-public-key')
    publicKey = res.public_key
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return 'not-configured'
    return 'error'
  }

  try {
    const permission = await Notification.requestPermission()
    if (permission !== 'granted') return 'denied'

    const registration = await navigator.serviceWorker.register('/sw.js')
    await navigator.serviceWorker.ready

    const existing = await registration.pushManager.getSubscription()
    const subscription =
      existing ??
      (await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      }))

    const json = subscription.toJSON()
    await apiClient.post('/push/subscribe', {
      endpoint: json.endpoint,
      keys: { p256dh: json.keys?.p256dh, auth: json.keys?.auth },
    })
    return 'subscribed'
  } catch {
    return 'error'
  }
}
