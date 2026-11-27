/** True when this browser can open a camera at all (it cannot on plain http:// pages other than localhost). */
export function cameraAvailable(): boolean {
  return typeof navigator !== 'undefined' && typeof window !== 'undefined' && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia
}
