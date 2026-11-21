// Shared between the page (DOM) and the 3D scene.
// Plain numbers only, with no three.js import, so the page can use it without loading the 3D chunk.

export const world = {
  /** current scroll position in px (written by the page, read by the camera rig) */
  scrollY: 0,
  /** named scroll positions in px (see journey.ts); measured by the page after layout */
  marks: {} as Record<string, number>,
  /** 0..1 progress through the pinned "how it works" section */
  howProgress: 0,
  /** the landing page has been let in (the intro gate has started to lift): the scene may now answer the pointer */
  entered: false,
  /**
   * The opening film (see film.ts): one camera move through the real scene, from far away (the hand as small as the
   * loader's drawing, so the two swap unseen) to the ordinary hero view. The intro gate owns the clock; everything
   * else here is derived from it each frame by the camera rig, and rests at the "ordinary" values (1, or 0 for
   * `props`) whenever there is no film.
   */
  film: {
    /** a film is being played on this visit: the scene waits in its opening shot until the gate starts the clock */
    on: false,
    /** seconds into the film (0 = loading has just reached 100%) */
    clock: 0,
    /** how much of the loading bar is filled (0..1): the hero hand draws itself in step with it, unseen behind the gate */
    load: 1,
    /** how fast the camera is flying right now, 0..1 (drives the stars' streaks) */
    speed: 0,
    /** where the flight is heading on the screen (0..1, y down): the streaks fly out of this point */
    vx: 0.5,
    vy: 0.5,
    /** how much of the galaxy is shown */
    sky: 1,
    /** how much of the hero hand's turn towards the viewer's right has been put back (0 = it faces the viewer, as drawn in the loader) */
    tilt: 1,
    /** how much the hand floats and follows the pointer, and the camera drifts (0 while the camera is on its way) */
    live: 1,
    /** how much lines quieten over the side of the screen where the headline will be */
    text: 1,
    /** how much of the film's own props (the zodiac wheel, the planet, the stars) may be shown: 1 until they fade away at the end, 0 when there is no film */
    props: 0,
    /** multiplies the width of the hand's lines, so they keep a steady weight on screen while the hand grows (a shared uniform) */
    boost: { value: 1 },
    /** how tall the loader's drawn hand is, in px (measured by the gate) */
    handPx: 187.2,
    /**
     * Where the film's planet is on the screen, so the stars' streaks (a flat layer above the scene) can pass behind it instead of
     * across it: [how much of it is shown (0..1), the body's centre x, y and radius in px, then the ring's outline as x, y pairs in px].
     * Empty while there is no planet. Filled in place, so it can be handed over once.
     */
    mask: [] as number[],
  },
  /** pointer position, -1..1 on both axes */
  pointer: { x: 0, y: 0 },
  /** portrait phone-like screen: lighter scene, centred objects */
  narrow: false,
  /** the visitor asked for less motion */
  reduced: false,
  /** 1 while text sits over the scene (lines quieten on the text side), easing to 0 for the open sunrise */
  safe: 1,
  /** bumped whenever the marks change so the camera re-resolves its keyframes */
  version: 0,
  /** which 3D object the pointer is over right now ('planet', 'zodiac:3', or '' for open sky); read by tests */
  hit: '',
}
