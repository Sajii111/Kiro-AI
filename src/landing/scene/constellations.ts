// The twelve zodiac constellations, drawn the way a star chart draws them: a handful of stars joined by lines.
// They are simplified on purpose (this is decoration for the scanning scene, not an astronomy chart).
// Each one sits in a box about 1.1 wide and 1 tall, centred on (0, 0), with "up" pointing away from the middle of the wheel.
// `lines` are chains of star numbers; `big` lists the brightest stars so they can be drawn larger.

export type Constellation = {
  name: string
  /** the traditional date range the sign covers */
  dates: string
  stars: [number, number][]
  lines: number[][]
  big?: number[]
}

export const CONSTELLATIONS: Constellation[] = [
  {
    name: 'Aries',
    dates: 'Mar 21 – Apr 19',
    stars: [[-0.52, -0.2], [-0.2, -0.04], [0.1, 0.1], [0.36, 0.1], [0.5, -0.12]],
    lines: [[0, 1, 2, 3, 4]],
    big: [2],
  },
  {
    name: 'Taurus',
    dates: 'Apr 20 – May 20',
    stars: [[-0.56, 0.44], [-0.34, 0.28], [-0.17, 0.1], [0, -0.1], [0.2, 0.08], [0.38, 0.22], [0.56, 0.42], [0.12, -0.38]],
    lines: [[0, 1, 2, 3, 4, 5, 6], [3, 7]],
    big: [3],
  },
  {
    name: 'Gemini',
    dates: 'May 21 – Jun 20',
    stars: [[-0.16, 0.5], [0.14, 0.47], [-0.2, 0.2], [-0.28, -0.1], [-0.36, -0.42], [0.16, 0.18], [0.24, -0.12], [0.32, -0.44]],
    lines: [[0, 2, 3, 4], [1, 5, 6, 7], [2, 5]],
    big: [0, 1],
  },
  {
    name: 'Cancer',
    dates: 'Jun 21 – Jul 22',
    stars: [[-0.34, -0.42], [0, 0], [0.42, -0.3], [-0.08, 0.28], [0.1, 0.5]],
    lines: [[0, 1, 2], [1, 3, 4]],
  },
  {
    name: 'Leo',
    dates: 'Jul 23 – Aug 22',
    stars: [[-0.46, -0.3], [-0.38, -0.05], [-0.26, 0.18], [-0.1, 0.32], [0.06, 0.28], [0.1, 0.1], [0.14, -0.14], [0.52, 0.04]],
    lines: [[0, 1, 2, 3, 4, 5, 6, 7, 5]],
    big: [0],
  },
  {
    name: 'Virgo',
    dates: 'Aug 23 – Sep 22',
    stars: [[-0.08, -0.5], [-0.02, -0.18], [0.14, 0.04], [0.42, 0.18], [-0.18, 0.1], [-0.4, 0.28], [-0.2, 0.42]],
    lines: [[0, 1, 2, 3], [1, 4, 5], [4, 6]],
    big: [0],
  },
  {
    name: 'Libra',
    dates: 'Sep 23 – Oct 22',
    stars: [[-0.42, 0.04], [0, 0.4], [0.4, 0.08], [0.04, -0.36], [-0.28, -0.3]],
    lines: [[0, 1, 2, 3, 0], [3, 4]],
  },
  {
    name: 'Scorpio',
    dates: 'Oct 23 – Nov 21',
    stars: [[-0.56, 0.36], [-0.44, 0.2], [-0.38, 0.04], [-0.26, -0.1], [-0.1, -0.2], [0.08, -0.3], [0.26, -0.38], [0.44, -0.28], [0.54, -0.1], [0.46, 0.06], [-0.26, 0.28]],
    lines: [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 10]],
    big: [3],
  },
  {
    name: 'Sagittarius',
    dates: 'Nov 22 – Dec 21',
    stars: [[-0.3, -0.28], [-0.34, 0.06], [-0.12, 0.26], [0.14, 0.24], [0.3, -0.04], [0.18, -0.34], [-0.56, 0.2], [0.52, 0.3]],
    lines: [[0, 1, 2, 3, 4, 5, 0], [1, 6], [3, 7]],
  },
  {
    name: 'Capricorn',
    dates: 'Dec 22 – Jan 19',
    stars: [[-0.54, 0.3], [0.54, 0.34], [0.04, -0.4], [-0.3, -0.12], [0.3, -0.1]],
    lines: [[0, 1], [0, 3, 2, 4, 1]],
  },
  {
    name: 'Aquarius',
    dates: 'Jan 20 – Feb 18',
    stars: [[-0.54, 0.18], [-0.3, 0.32], [-0.06, 0.14], [0.18, 0.3], [0.5, 0.1], [-0.4, -0.2], [-0.12, -0.36], [0.2, -0.22], [0.48, -0.4]],
    lines: [[0, 1, 2, 3, 4], [5, 6, 7, 8]],
  },
  {
    name: 'Pisces',
    dates: 'Feb 19 – Mar 20',
    stars: [[-0.56, 0.1], [-0.4, 0.3], [-0.22, 0.2], [-0.34, 0], [0.56, 0.1], [0.4, 0.3], [0.22, 0.2], [0.34, 0], [0, -0.34]],
    lines: [[0, 1, 2, 3, 0], [4, 5, 6, 7, 4], [3, 8, 7]],
  },
]
