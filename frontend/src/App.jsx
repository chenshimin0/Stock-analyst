import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import ReportDetail from './pages/ReportDetail';
import WinRateAnalysis from './pages/WinRateAnalysis';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/reports/:slug" element={<ReportDetail />} />
          <Route path="/winrate" element={<WinRateAnalysis />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
