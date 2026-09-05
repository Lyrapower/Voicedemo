import React, { useEffect, useState } from 'react'
import Console from './pages/Console.jsx'
import Alpha from './pages/Alpha.jsx'
import Field from './pages/Field.jsx'

const ROUTES = { console: ['运维台', Console], alpha: ['ALPHA 工坊', Alpha], field: ['粒子场', Field] }

export default function App() {
  const [route, setRoute] = useState(location.hash.replace('#/', '') || 'console')
  useEffect(() => {
    const f = () => setRoute(location.hash.replace('#/', '') || 'console')
    addEventListener('hashchange', f); return () => removeEventListener('hashchange', f)
  }, [])
  const Page = (ROUTES[route] || ROUTES.console)[1]
  return (<>
    <nav>
      <span className="brand">ALPHA PLATFORM</span>
      {Object.entries(ROUTES).map(([k, [label]]) =>
        <a key={k} href={'#/' + k} className={route === k ? 'on' : ''}>{label}</a>)}
      <span className="dim" style={{ marginLeft: 'auto', fontSize: 11 }}>v0.7 · paper only · broker=false</span>
    </nav>
    <main><Page /></main>
  </>)
}
