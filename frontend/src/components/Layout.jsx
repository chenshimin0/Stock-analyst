import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const linkClass = ({ isActive }) => isActive ? 'active' : '';

  const closeSidebar = () => setSidebarOpen(false);

  return (
    <div className="layout">
      <button className="hamburger" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="菜单">
        <span /><span /><span />
      </button>
      {sidebarOpen && <div className="sidebar-overlay" onClick={closeSidebar} />}
      <nav className="sidebar" data-open={sidebarOpen}>
        <div className="logo">A股分析系统</div>
        <NavLink to="/" className={linkClass} end onClick={closeSidebar}>报告列表</NavLink>
        <NavLink to="/winrate" className={linkClass} onClick={closeSidebar}>胜率分析</NavLink>
        <NavLink to="/sector-tracker" className={linkClass} onClick={closeSidebar}>📊 板块追踪</NavLink>
      </nav>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
