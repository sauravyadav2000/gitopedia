import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import StreamingMarkdown from '@/components/StreamingMarkdown';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { ArrowLeft, Save, Eye, Pencil, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { motion } from 'framer-motion';

const API = process.env.REACT_APP_BACKEND_URL;

export default function EditReport() {
  const { id } = useParams();
  const { user, getToken, refreshProfile } = useAuth();
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState('edit');

  useEffect(() => {
    if (!user) {
      navigate(`/auth?redirect=/edit/${id}`);
      return;
    }
    fetchReport();
  }, [user, id]);

  const fetchReport = async () => {
    try {
      const res = await fetch(`${API}/api/reports/${id}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setReport(data);
      setContent(data.content);
    } catch {
      navigate('/dashboard');
    }
    setLoading(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const token = await getToken();
      const res = await fetch(`${API}/api/reports/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ content }),
      });
      if (res.status === 402) {
        toast.error('Insufficient credits. You need 1 credit to edit.');
        setSaving(false);
        return;
      }
      if (!res.ok) {
        const err = await res.json();
        toast.error(err.detail || 'Failed to save');
        setSaving(false);
        return;
      }
      const data = await res.json();
      refreshProfile();
      toast.success(`Report updated. ${data.credits_remaining} credits remaining.`);
      navigate(`/report/${id}`);
    } catch {
      toast.error('Save failed');
    }
    setSaving(false);
  };

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-6 py-12 space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-[500px] w-full" />
      </div>
    );
  }

  if (!report) return null;

  return (
    <div className="min-h-[calc(100vh-4rem)] px-6 py-8">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="sm" onClick={() => navigate(-1)} className="text-muted-foreground" data-testid="back-button">
              <ArrowLeft className="w-4 h-4 mr-1" /> Back
            </Button>
            <div>
              <p className="text-sm text-muted-foreground tracking-widest uppercase font-mono">Editing</p>
              <h1 className="text-xl font-heading font-bold">{report.repo_full_name}</h1>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="hidden sm:flex items-center bg-muted/50 rounded-sm p-0.5">
              <button
                onClick={() => setTab('edit')}
                className={`px-3 py-1.5 text-sm rounded-sm transition-colors ${tab === 'edit' ? 'bg-card text-foreground' : 'text-muted-foreground'}`}
                data-testid="edit-tab"
              >
                <Pencil className="w-3.5 h-3.5 inline mr-1" /> Edit
              </button>
              <button
                onClick={() => setTab('preview')}
                className={`px-3 py-1.5 text-sm rounded-sm transition-colors ${tab === 'preview' ? 'bg-card text-foreground' : 'text-muted-foreground'}`}
                data-testid="preview-tab"
              >
                <Eye className="w-3.5 h-3.5 inline mr-1" /> Preview
              </button>
            </div>
            <Button onClick={handleSave} disabled={saving}
              className="bg-primary text-primary-foreground hover:bg-primary/90 font-bold rounded-sm"
              data-testid="save-button">
              {saving ? <><Loader2 className="w-4 h-4 mr-1 animate-spin" /> Saving...</> : <><Save className="w-4 h-4 mr-1" /> Save (1 credit)</>}
            </Button>
          </div>
        </div>

        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
          {tab === 'edit' ? (
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="w-full min-h-[calc(100vh-12rem)] bg-card/50 border border-border/50 rounded-sm p-6 text-sm font-mono text-foreground resize-none focus:outline-none focus:border-primary/50 leading-relaxed"
              placeholder="Markdown content..."
              data-testid="edit-textarea"
            />
          ) : (
            <Card className="bg-card/30 border-border/50">
              <CardContent className="p-6 md:p-10 min-h-[calc(100vh-12rem)]">
                <StreamingMarkdown content={content} isStreaming={false} />
              </CardContent>
            </Card>
          )}
        </motion.div>
      </div>
    </div>
  );
}
