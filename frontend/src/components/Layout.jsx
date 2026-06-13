import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';

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
        <Submenu label="🎯 策略" paths={['/strategies', '/strategy']} onNavigate={closeSidebar}>
          <NavLink to="/strategies" className={linkClass} onClick={closeSidebar}>策略定义</NavLink>
          <NavLink to="/strategy" className={linkClass} end onClick={closeSidebar}>策略批次</NavLink>
        </Submenu>
      </nav>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}

function Submenu({ label, paths, onNavigate, children }) {
  const location = useLocation();
  // Auto-open if current path matches any of the child paths
  const isChildActive = paths.some(p =>
    location.pathname === p || location.pathname.startsWith(p + '/')
  );
  const [open, setOpen] = useState(isChildActive);

  // If user navigates between children, keep it open
  if (isChildActive && !open) {
    setOpen(true);
  }

  return (
    <div className="submenu">
      <div
        className={`submenu-header ${isChildActive ? 'active' : ''}`}
        onClick={() => setOpen(!open)}
        role="button"
        tabIndex={0}
        onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && setOpen(!open)}
      >
        <span>{label}</span>
        <span className="submenu-arrow">{open ? '▾' : '▸'}</span>
      </div>
      {open && <div className="submenu-children" onClick={onNavigate}>{children}</div>}
    </div>
  );
}
