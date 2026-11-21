// Apply the saved theme before the first paint so there is no light/dark flash.
// Night Sky (dark) is the default; only an explicit choice of Golden Hour (light) is remembered as light.
//
// This is a file of its own, not an inline <script>, because the server's content security policy
// (script-src 'self') does not allow inline scripts. index.html loads it first, before anything is painted.
try {
  var light = localStorage.getItem('kiro-theme-v2') === 'light'
  document.documentElement.dataset.theme = light ? 'light' : 'dark'
  document.querySelector('meta[name="theme-color"]').setAttribute('content', light ? '#FFF4E8' : '#080B1C')
} catch {
  document.documentElement.dataset.theme = 'dark'
}
