import { NavLink, Route, Routes } from 'react-router-dom'
import ConnectPage from './pages/ConnectPage.jsx'
import InstructionPage from './pages/InstructionPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import ReviewPage from './pages/ReviewPage.jsx'
import ApplyPage from './pages/ApplyPage.jsx'

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Limpmail</div>
        <nav>
          <NavLink to="/" end>Conectar</NavLink>
          <NavLink to="/instrucao">Instrução</NavLink>
          <NavLink to="/progresso">Progresso</NavLink>
          <NavLink to="/revisao">Revisão</NavLink>
          <NavLink to="/aplicar">Aplicar</NavLink>
        </nav>
      </header>
      <main className="content">
        <Routes>
          <Route path="/" element={<ConnectPage />} />
          <Route path="/instrucao" element={<InstructionPage />} />
          <Route path="/progresso" element={<DashboardPage />} />
          <Route path="/revisao" element={<ReviewPage />} />
          <Route path="/aplicar" element={<ApplyPage />} />
        </Routes>
      </main>
    </div>
  )
}
