// How sure we are about a palm feature (the PDF's "detected / uncertain / not visible").
// The same three words are used by the API contract, the annotated image and the report.

export type FeatureStatus = 'detected' | 'uncertain' | 'not_visible'

export const STATUS_LABEL: Record<FeatureStatus, string> = {
  detected: 'Detected',
  uncertain: 'Uncertain',
  not_visible: 'Not visible',
}
