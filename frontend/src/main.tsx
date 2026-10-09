import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './base.css'
import { Community } from './Community'
import { ToCommunity } from './ToCommunity'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/community/*" element={<Community />} />
        <Route path="*" element={<ToCommunity />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
