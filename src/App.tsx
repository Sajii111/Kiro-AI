import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import NotFound from './app/NotFound'
import RequireSession from './app/RequireSession'
import Splash from './app/Splash'
import Cosmos from './components/Cosmos'
import Cursor from './components/Cursor'
import RouteStage from './components/RouteStage'
import SparkleTrail from './components/SparkleTrail'
import SoundToggle from './components/SoundToggle'
import { ToastProvider } from './components/ui/Toast'
import Landing from './pages/Landing'
import NotBuilt from './pages/NotBuilt'
import { DataProvider } from './state/data'
import { SessionProvider } from './state/session'
import { UiProvider } from './state/ui'
import { t } from './i18n'

// The landing page is cinematic and loads first. The app screens load on demand.
const SignIn = lazy(() => import('./pages/SignIn'))
const StartGuest = lazy(() => import('./app/StartGuest'))
const AppShell = lazy(() => import('./app/AppShell'))
const ProfileGate = lazy(() => import('./app/ProfileGate'))
const RequireProfile = lazy(() => import('./app/ProfileGate').then((m) => ({ default: m.RequireProfile })))
const NewReading = lazy(() => import('./app/NewReading'))
const ReadingPage = lazy(() => import('./app/ReadingPage'))
const ChatPage = lazy(() => import('./app/ChatPage'))
const History = lazy(() => import('./app/History'))
const Settings = lazy(() => import('./app/Settings'))
const UnlockPage = lazy(() => import('./app/palm/UnlockPage'))
const LockSetup = lazy(() => import('./app/palm/LockSetup'))
const SecurityPage = lazy(() => import('./app/palm/SecurityPage'))
const PalmLab = lazy(() => import('./app/palm/PalmLab'))

/** The custom cursor and the floating sound button belong to the landing page only; the app stays plain and calm. */
function LandingExtras({ landing }: { landing: boolean }) {
  return landing ? (
    <>
      <Cursor />
      <SoundToggle />
    </>
  ) : null
}

export default function App() {
  return (
    <UiProvider>
      <SessionProvider>
        <ToastProvider>
          <DataProvider>
            <BrowserRouter>
              {/* the starry sky and the sparkle trail belong to every page */}
              <Cosmos />
              <SparkleTrail />
              {/* pages change behind a short veil (components/RouteStage.tsx); `shown` is the page on screen */}
              <RouteStage>
                {(shown) => (
                  <>
                    <LandingExtras landing={shown.pathname === '/'} />
                    <Suspense fallback={<Splash />}>
                      <Routes location={shown}>
                        <Route path="/" element={<Landing />} />
                        <Route path="/signin" element={<SignIn />} />
                        <Route path="/start" element={<StartGuest />} />
                        <Route
                          path="/app"
                          element={
                            <RequireSession>
                              <AppShell />
                            </RequireSession>
                          }
                        >
                          {/* the profile picker, then the chosen profile's home */}
                          <Route index element={<ProfileGate />} />
                          {/* the pages inside one profile: without an open profile they send the person to choose one */}
                          <Route
                            path="new"
                            element={
                              <RequireProfile>
                                <NewReading />
                              </RequireProfile>
                            }
                          />
                          <Route
                            path="readings/:id"
                            element={
                              <RequireProfile>
                                <ReadingPage />
                              </RequireProfile>
                            }
                          />
                          <Route
                            path="chat"
                            element={
                              <RequireProfile>
                                <ChatPage />
                              </RequireProfile>
                            }
                          />
                          <Route
                            path="history"
                            element={
                              <RequireProfile>
                                <History />
                              </RequireProfile>
                            }
                          />
                          <Route path="settings" element={<Settings />} />
                          <Route path="unlock/:id" element={<UnlockPage />} />
                          <Route path="lock/:id" element={<LockSetup />} />
                          <Route
                            path="security"
                            element={
                              <RequireProfile>
                                <SecurityPage />
                              </RequireProfile>
                            }
                          />
                          <Route path="palm-lab" element={<PalmLab />} />
                          <Route path="*" element={<NotFound />} />
                        </Route>
                        <Route path="*" element={<NotBuilt title={t("Nothing here")} note={t("That page does not exist.")} />} />
                      </Routes>
                    </Suspense>
                  </>
                )}
              </RouteStage>
            </BrowserRouter>
          </DataProvider>
        </ToastProvider>
      </SessionProvider>
    </UiProvider>
  )
}
