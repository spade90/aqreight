import Chat from '../components/Chat';
import AdminPanel from '../components/AdminPanel';

export default function Page() {
  return (
    <div className="app">
      <header className="topbar">
        <span className="topbarLogo">◉</span>
        <span className="topbarTitle">AI Policy Helper</span>
      </header>
      <main className="workspace">
        <AdminPanel />
        <Chat />
      </main>
    </div>
  );
}
