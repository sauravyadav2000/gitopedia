import { useState, useEffect, useRef } from 'react';
import { useSearchParams, useNavigate, Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import StreamingMarkdown from '@/components/StreamingMarkdown';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Loader2, AlertCircle, CheckCircle2, ExternalLink, ArrowRight } from 'lucide-react';
import { motion } from 'framer-motion';

const API = process.env.REACT_APP_BACKEND_URL;

export default function Generate() {
  const [searchParams] = useSearchParams();
  const url = searchParams.get('url') || '';
  const { user, getToken, refreshProfile } = useAuth();
  const navigate = useNavigate();

  const [status, setStatus] = useState('');
  const [content, setContent] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState('');
  const [reportId, setReportId] = useState('');
  const [existingReport, setExistingReport] = useState(null);
  const [creditsRemaining, setCreditsRemaining] = useState(null);
  const startedRef = useRef(false);
  const contentRef = useRef(null);

  useEffect(() => {
    if (!user) {
      navigate(`/auth?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`);
      return;
    }
    if (url && !startedRef.current) {
      startedRef.current = true;
      startGeneration();
    }
  }, [user, url]);

  useEffect(() => {
    if (contentRef.current && isStreaming) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [content, isStreaming]);

  const startGeneration = async () => {
    setError('');
    setContent('');
    setStatus('Initializing...');
    setIsStreaming(true);
    setExistingReport(null);

    try {
      const token = await getToken();
      const response = await fetch(`${API}/api/reports/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ repo_url: url }),
      });

      if (!response.ok) {
        if (response.status === 402) {
          setError('Insufficient credits. You need 2 credits to generate a report.');
          setIsStreaming(false);
          return;
        }
        const errData = await response.json();
        setError(errData.detail || 'Failed to generate report');
        setIsStreaming(false);
        return;
      }

      const contentType = response.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        const data = await response.json();
        if (data.exists) {
          setExistingReport(data.report);
          setIsStreaming(false);
          return;
        }
      }

      // SSE stream
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
            if (data.type === 'status') {
              setStatus(data.message);
            } else if (data.type === 'content') {
              setContent(prev => prev + data.text);
            } else if (data.type === 'done') {
              setReportId(data.report_id);
              setCreditsRemaining(data.credits_remaining);
              setIsStreaming(false);
              setStatus('');
              refreshProfile();
            } else if (data.type === 'error') {
              setError(data.message);
              setIsStreaming(false);
              setStatus('');
            }
          } catch {}
        }
      }
    } catch (e) {
      setError('Connection error. Please try again.');
      setIsStreaming(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] px-6 py-8">
      <div className="max-w-4xl mx-auto">
        {/* Existing report banner */}
        {existingReport && (
          <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
            <Card className="mb-6 border-primary/30 bg-primary/5" data-testid="existing-report-banner">
              <CardContent className="p-4 flex items-center justify-between gap-4">
                <div>
                  <p className="font-heading font-semibold text-foreground">
                    A report for this repo already exists
                  </p>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    View it for free or spend 2 credits to regenerate with latest data.
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  <Button variant="outline" size="sm" onClick={() => navigate(`/report/${existingReport.id}`)}
                    data-testid="view-existing-report">
                    View Report <ExternalLink className="w-3 h-3 ml-1" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {/* Error */}
        {error && (
          <Card className="mb-6 border-destructive/30 bg-destructive/5" data-testid="generation-error">
            <CardContent className="p-4 flex items-center gap-3">
              <AlertCircle className="w-5 h-5 text-destructive shrink-0" />
              <div>
                <p className="text-sm text-foreground">{error}</p>
                {error.includes('credits') && (
                  <Button variant="link" size="sm" className="text-primary p-0 h-auto mt-1" onClick={() => navigate('/credits')}>
                    Buy credits <ArrowRight className="w-3 h-3 ml-1" />
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Status */}
        {isStreaming && status && (
          <div className="flex items-center gap-3 mb-6 text-sm text-muted-foreground" data-testid="generation-status">
            <Loader2 className="w-4 h-4 animate-spin text-primary" />
            <span>{status}</span>
          </div>
        )}

        {/* Header */}
        <div className="mb-6">
          <p className="text-sm text-muted-foreground tracking-widest uppercase font-mono mb-1">
            {isStreaming ? 'Generating' : reportId ? 'Complete' : 'Report'}
          </p>
          <h1 className="text-2xl md:text-3xl font-heading font-bold tracking-tight flex items-center gap-3">
            {url.replace(/https?:\/\/github\.com\//, '')}
            {reportId && <CheckCircle2 className="w-6 h-6 text-accent" />}
          </h1>
        </div>

        {/* Streaming content */}
        {(content || isStreaming) && (
          <Card className="bg-card/50 backdrop-blur-md border-border/50">
            <CardContent className="p-6 md:p-8" ref={contentRef}>
              <StreamingMarkdown content={content} isStreaming={isStreaming} />
            </CardContent>
          </Card>
        )}

        {/* Actions after completion */}
        {reportId && !isStreaming && (
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 flex items-center gap-4">
            <Button onClick={() => navigate(`/report/${reportId}`)} className="bg-primary text-primary-foreground hover:bg-primary/90 font-bold rounded-sm"
              data-testid="view-full-report">
              View Full Report <ArrowRight className="w-4 h-4 ml-1" />
            </Button>
            {creditsRemaining !== null && (
              <span className="text-sm text-muted-foreground">
                {creditsRemaining} credits remaining
              </span>
            )}
          </motion.div>
        )}
      </div>
    </div>
  );
}
