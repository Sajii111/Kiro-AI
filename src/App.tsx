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

// The landing page is cinematic and loads first. The app screens load on demand.
const SignIn = lazy(() => import('./pages/SignIn'))
const StartGuest = lazy(() => import('./app/StartGuest'))
const AppShell = lazy(() => import('./app/AppShell'))
const Dashboard = lazy(() => import('./app/Dashboard'))
const NewReading = lazy(() => import('./app/NewReading'))
const ReadingPage = lazy(() => import('./app/ReadingPage'))
const ChatPage = lazy(() => import('./app/ChatPage'))
const History = lazy(() => import('./app/History'))
const Settings = lazy(() => import('./app/Settings'))

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
                          <Route index element={<Dashboard />} />
                          <Route path="new" element={<NewReading />} />
                          <Route path="readings/:id" element={<ReadingPage />} />
                          <Route path="chat" element={<ChatPage />} />
                          <Route path="history" element={<History />} />
                          <Route path="settings" element={<Settings />} />
                          <Route path="*" element={<NotFound />} />
                        </Route>
                        <Route path="*" element={<NotBuilt title="Nothing here" note="That page does not exist." />} />
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
