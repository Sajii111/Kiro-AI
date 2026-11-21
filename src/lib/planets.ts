import { hashString } from './rand'

// Every hand profile is drawn as its own little planet (see PlanetAvatar). There are six colours and three shapes
// (plain, ringed, with a moon), so 18 different worlds. A planet is a number from 0 to 17: colour = n % 6, shape = n / 6.

export const PLANET_COUNT = 18

/** The planet an id would pick for itself. The same id always asks for the same one. */
export function preferredPlanet(id: string): number {
  const h = hashString(id)
  return (h % 6) + 6 * ((h >>> 5) % 3)
}

/**
 * Gives each profile of an account a planet of its own.
 *
 * A profile keeps the planet its id picks, unless an older profile of the same account already wears it, and then it
 * moves on to the next free one. Going in order of creation means a new profile can never change the planet of an older
 * one, and the answer only depends on the list, so a profile looks the same on every screen. (Past 18 profiles the
 * planets have to repeat.)
 */
export function assignPlanets(profiles: ReadonlyArray<{ id: string; createdAt: string }>): Map<string, number> {
  const order = [...profiles].sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id))
  const taken = new Set<number>()
  const planets = new Map<string, number>()
  for (const profile of order) {
    let planet = preferredPlanet(profile.id)
    // 7 and 18 share no factor, so stepping by 7 visits every planet, and each step changes both the colour and the shape
    for (let tries = 0; taken.has(planet) && tries < PLANET_COUNT; tries++) planet = (planet + 7) % PLANET_COUNT
    taken.add(planet)
    planets.set(profile.id, planet)
  }
  return planets
}
