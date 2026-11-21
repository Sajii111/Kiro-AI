import type { FeatureId } from '../api/types'

/** The five principal lines, in the order they are listed and numbered everywhere. */
export const FEATURE_ORDER: FeatureId[] = ['heart', 'head', 'life', 'fate', 'sun']

/** 1 to 5: the number shown on the line's badge. */
export const featureNumber = (id: FeatureId): number => FEATURE_ORDER.indexOf(id) + 1
