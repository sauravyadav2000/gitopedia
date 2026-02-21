import '@/App.css';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from '@/contexts/AuthContext';
import { Toaster } from '@/components/ui/sonner';
import Header from '@/components/Header';
import Landing from '@/pages/Landing';
import Auth from '@/pages/Auth';
import Generate from '@/pages/Generate';
import ReportView from '@/pages/ReportView';
import Browse from '@/pages/Browse';
import Dashboard from '@/pages/Dashboard';
import Credits from '@/pages/Credits';
import EditReport from '@/pages/EditReport';

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <div className="min-h-screen bg-background text-foreground">
          <Header />
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/auth" element={<Auth />} />
            <Route path="/generate" element={<Generate />} />
            <Route path="/report/:id" element={<ReportView />} />
            <Route path="/browse" element={<Browse />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/credits" element={<Credits />} />
            <Route path="/credits/success" element={<Credits />} />
            <Route path="/edit/:id" element={<EditReport />} />
          </Routes>
          <Toaster position="bottom-right" theme="dark" />
        </div>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
