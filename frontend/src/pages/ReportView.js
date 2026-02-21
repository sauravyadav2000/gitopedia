import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import StreamingMarkdown from '@/components/StreamingMarkdown';
import OwnershipBanner from '@/components/OwnershipBanner';
import UpgradeAlert from '@/components/UpgradeAlert';
import VersionHistory from '@/components/VersionHistory';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { Star, GitFork, ExternalLink, RefreshCw, Pencil, Clock, ArrowLeft, Share2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

export default function ReportView() {
  const { id } = useParams();
  const { user, getToken, refreshProfile } = useAuth();
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [upgrading, setUpgrading] = useState(false);
  const [upgradeInfo, setUpgradeInfo] = useState(null);
  const [regenerating, setRegenerating] = useState(false);
  const [regenContent, setRegenContent] = useState('');
  const [toc, setToc] = useState([]);

  useEffect(() => {
    fetchReport();
  }, [id]);

  useEffect(() => {
    if (report?.content) {
      const headings = report.content.match(/^## (.+)$/gm) || [];
      setToc(headings.map(h => h.replace('## ', '')));
    }
  }, [report?.content]);

  const fetchReport = async () => {
    try {
      const res = await fetch(`${API}/api/reports/${id}`);
      if (!res.ok) throw new Error('Report not found');
      setReport(await res.json());
    } catch {
      navigate('/browse');
    }
    setLoading(false);
  };

  const handleRegenerate = async () => {
    if (!user) {
      navigate(`/auth?redirect=/report/${id}`);
      return;
    }
    setRegenerating(true);
    setRegenContent('');
    try {
      const token = await getToken();
      const response = await fetch(`${API}/api/reports/${id}/regenerate`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.status === 402) {
        toast.error('Insufficient credits. You need 2 credits to regenerate.');
        setRegenerating(false);
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'content') setRegenContent(prev => prev + data.text);
            else if (data.type === 'done') {
              setRegenerating(false);
              refreshProfile();
              fetchReport();
              toast.success('Report regenerated successfully');
            } else if (data.type === 'error') {
              toast.error(data.message);
              setRegenerating(false);
            }
          } catch {}
        }
      }
    } catch {
      toast.error('Regeneration failed');
      setRegenerating(false);
    }
  };

  const scrollToSection = (heading) => {
    const el = document.querySelector(`[data-heading="${heading}"]`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href);
    toast.success('Link copied to clipboard');
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-12 space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-96" />
        <Skeleton className="h-[400px] w-full" />
      </div>
    );
  }

  if (!report) return null;

  const displayContent = regenerating ? regenContent : report.content;

  return (
    <div className="min-h-[calc(100vh-4rem)]">
      <div className="max-w-7xl mx-auto px-6 py-8 lg:grid lg:grid-cols-12 lg:gap-8">
        {/* TOC sidebar */}
        <aside className="hidden lg:block lg:col-span-3">
          <div className="sticky top-24">
            <p className="text-xs text-muted-foreground tracking-widest uppercase font-mono mb-3">Contents</p>
            <nav className="space-y-1">
              {toc.map((heading) => (
                <button
                  key={heading}
                  onClick={() => scrollToSection(heading)}
                  className="block text-sm text-muted-foreground hover:text-foreground transition-colors duration-200 text-left py-1 truncate w-full"
                  data-testid={`toc-${heading.toLowerCase().replace(/\s+/g, '-')}`}
                >
                  {heading}
                </button>
              ))}
            </nav>
          </div>
        </aside>

        {/* Main content */}
        <main className="lg:col-span-9">
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
            {/* Header */}
            <div className="mb-8 no-print">
              <Button variant="ghost" size="sm" onClick={() => navigate(-1)} className="text-muted-foreground mb-4" data-testid="back-button">
                <ArrowLeft className="w-4 h-4 mr-1" /> Back
              </Button>

              <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
                <div>
                  <h1 className="text-3xl md:text-4xl font-heading font-bold tracking-tight" data-testid="report-title">
                    {report.repo_full_name}
                  </h1>
                  {report.description && (
                    <p className="text-base text-muted-foreground mt-2 max-w-xl">{report.description}</p>
                  )}
                  <div className="flex items-center gap-4 mt-3 text-sm text-muted-foreground flex-wrap">
                    <span className="flex items-center gap-1"><Star className="w-3.5 h-3.5" /> {report.stars?.toLocaleString()}</span>
                    <span className="flex items-center gap-1"><GitFork className="w-3.5 h-3.5" /> {report.forks?.toLocaleString()}</span>
                    {report.language && <Badge variant="secondary" className="text-xs">{report.language}</Badge>}
                    <span className="flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5" /> v{report.version || 1}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Button variant="outline" size="sm" onClick={handleShare} data-testid="share-button">
                    <Share2 className="w-4 h-4 mr-1" /> Share
                  </Button>
                  <a href={report.repo_url} target="_blank" rel="noopener noreferrer">
                    <Button variant="outline" size="sm" data-testid="github-link">
                      <ExternalLink className="w-4 h-4 mr-1" /> GitHub
                    </Button>
                  </a>
                  {user && (
                    <>
                      <Button variant="outline" size="sm" onClick={handleRegenerate}
                        disabled={regenerating} data-testid="regenerate-button">
                        <RefreshCw className={`w-4 h-4 mr-1 ${regenerating ? 'animate-spin' : ''}`} />
                        {regenerating ? 'Regenerating...' : 'Regenerate (2 cr)'}
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => navigate(`/edit/${report.id}`)} data-testid="edit-button">
                        <Pencil className="w-4 h-4 mr-1" /> Edit (1 cr)
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </div>

            <Separator className="mb-8 no-print" />

            {/* Report content */}
            <div className="bg-card/30 border border-border/50 rounded-sm p-6 md:p-10">
              <StreamingMarkdown content={displayContent} isStreaming={regenerating} />
            </div>
          </motion.div>
        </main>
      </div>
    </div>
  );
}
