import type { SplitText } from 'gsap/SplitText'

/**
 * SplitText masks clip to the line box, which cuts the descenders off tight display type
 * ("gently", "y", "g"). Give each mask a little room above and below without moving the text.
 */
export function unclip(split: SplitText) {
  split.masks.forEach((mask) => {
    const el = mask as HTMLElement
    el.style.paddingTop = '0.08em'
    el.style.marginTop = '-0.08em'
    el.style.paddingBottom = '0.18em'
    el.style.marginBottom = '-0.18em'
  })
}
