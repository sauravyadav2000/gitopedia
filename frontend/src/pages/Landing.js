import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ArrowRight, Star, GitFork, Zap, Search, BookOpen, Code2, FileText } from 'lucide-react';
import { motion } from 'framer-motion';

const API = process.env.REACT_APP_BACKEND_URL;

export default function Landing() {
  const [repoUrl, setRepoUrl] = useState('');
  const [recentReports, setRecentReports] = useState([]);
  const [stats, setStats] = useState({ total_reports: 0, total_users: 0 });
  const [checking, setChecking] = useState(false);
  const { user } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    fetch(`${API}/api/reports?limit=6`).then(r => r.json()).then(d => setRecentReports(d.reports || [])).catch(() => {});
    fetch(`${API}/api/stats`).then(r => r.json()).then(setStats).catch(() => {});
  }, []);

  const handleAnalyze = async () => {
    if (!repoUrl.trim()) return;
    setChecking(true);
    try {
      const res = await fetch(`${API}/api/reports/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl }),
      });
      const data = await res.json();
      if (data.exists) {
        navigate(`/report/${data.report.id}`);
      } else if (user) {
        navigate(`/generate?url=${encodeURIComponent(repoUrl)}`);
      } else {
        navigate(`/auth?redirect=${encodeURIComponent(`/generate?url=${encodeURIComponent(repoUrl)}`)}`);
      }
    } catch {
      if (user) {
        navigate(`/generate?url=${encodeURIComponent(repoUrl)}`);
      } else {
        navigate(`/auth?redirect=${encodeURIComponent(`/generate?url=${encodeURIComponent(repoUrl)}`)}`);
      }
    }
    setChecking(false);
  };

  return (
    <div className="min-h-[calc(100vh-4rem)]">
      {/* Hero */}
      <section className="relative py-20 md:py-32 px-6">
        <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-12 items-center">
          <motion.div
            className="lg:col-span-7"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            <p className="text-sm text-muted-foreground tracking-widest uppercase mb-4 font-mono">
              Repository Intelligence
            </p>
            <h1 className="text-5xl md:text-7xl font-bold tracking-tight font-heading leading-[1.05]">
              Understand any
              <br />
              <span className="text-primary">GitHub repo</span>
              <br />
              in seconds.
            </h1>
            <p className="text-base md:text-lg text-muted-foreground leading-relaxed mt-6 max-w-xl">
              Paste a repo URL. Get a structured, AI-generated Markdown report
              covering architecture, tech stack, deployment, and more.
              Free to read. Community-driven.
            </p>

            <div className="mt-8 flex flex-col sm:flex-row gap-3 max-w-2xl">
              <div className="flex-1 relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="https://github.com/owner/repo"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
                  className="pl-10 h-12 bg-muted/50 border-transparent focus:border-primary text-foreground placeholder:text-muted-foreground"
                  data-testid="repo-url-input"
                />
              </div>
              <Button
                onClick={handleAnalyze}
                disabled={checking || !repoUrl.trim()}
                className="h-12 px-6 bg-primary text-primary-foreground hover:bg-primary/90 rounded-sm font-bold tracking-wide gap-2"
                data-testid="analyze-button"
              >
                {checking ? 'Checking...' : 'Analyze'}
                <ArrowRight className="w-4 h-4" />
              </Button>
            </div>

            <div className="mt-6 flex items-center gap-6 text-sm text-muted-foreground">
              <div className="flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5 text-primary" />
                <span>3 free credits on signup</span>
              </div>
              <div className="flex items-center gap-1.5">
                <BookOpen className="w-3.5 h-3.5 text-accent" />
                <span>Reports are free to read</span>
              </div>
            </div>
          </motion.div>

          <motion.div
            className="lg:col-span-5 hidden lg:block"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            <div className="relative">
              <div className="bg-card border border-border rounded-sm p-6 font-mono text-sm space-y-2">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-3 h-3 rounded-full bg-destructive/60" />
                  <div className="w-3 h-3 rounded-full bg-yellow-500/60" />
                  <div className="w-3 h-3 rounded-full bg-accent/60" />
                  <span className="ml-2 text-xs text-muted-foreground">report.md</span>
                </div>
                <p className="text-primary">## Overview</p>
                <p className="text-muted-foreground text-xs leading-relaxed">
                  A high-performance web framework built with Rust...
                </p>
                <p className="text-primary mt-3">## Tech Stack</p>
                <p className="text-muted-foreground text-xs">| Layer | Technology | Purpose |</p>
                <p className="text-muted-foreground text-xs">| Backend | Rust | Core runtime |</p>
                <p className="text-primary mt-3">## Architecture</p>
                <p className="text-muted-foreground text-xs leading-relaxed">
                  Event-driven architecture with async I/O...
                </p>
              </div>
              <div className="absolute -bottom-3 -right-3 w-full h-full border border-primary/20 rounded-sm -z-10" />
            </div>
          </motion.div>
        </div>
      </section>

      {/* Stats */}
      <section className="border-y border-border/50 bg-muted/20">
        <div className="max-w-7xl mx-auto px-6 py-8 grid grid-cols-3 gap-8">
          {[
            { label: 'Reports Generated', value: stats.total_reports, icon: FileText },
            { label: 'Community Members', value: stats.total_users, icon: Code2 },
            { label: 'Free to Read', value: 'Always', icon: BookOpen },
          ].map((s) => (
            <div key={s.label} className="text-center">
              <s.icon className="w-5 h-5 text-primary mx-auto mb-2" />
              <p className="text-2xl md:text-3xl font-heading font-bold">{s.value}</p>
              <p className="text-xs text-muted-foreground tracking-widest uppercase mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Recent Reports */}
      {recentReports.length > 0 && (
        <section className="py-16 px-6">
          <div className="max-w-7xl mx-auto">
            <div className="flex items-center justify-between mb-8">
              <div>
                <p className="text-sm text-muted-foreground tracking-widest uppercase font-mono mb-1">Latest</p>
                <h2 className="text-3xl md:text-4xl font-heading font-semibold tracking-tight">Recent Reports</h2>
              </div>
              <Button variant="ghost" onClick={() => navigate('/browse')} className="text-muted-foreground" data-testid="view-all-reports">
                View All <ArrowRight className="w-4 h-4 ml-1" />
              </Button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {recentReports.map((report, i) => (
                <motion.div
                  key={report.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                >
                  <Card
                    className="bg-card/50 backdrop-blur-md border-border/50 hover:border-primary/30 transition-all duration-300 cursor-pointer group"
                    onClick={() => navigate(`/report/${report.id}`)}
                    data-testid={`report-card-${report.id}`}
                  >
                    <CardContent className="p-5">
                      <div className="flex items-start justify-between mb-3">
                        <h3 className="font-heading font-semibold text-foreground group-hover:text-primary transition-colors truncate pr-2">
                          {report.repo_full_name}
                        </h3>
                        {report.language && (
                          <Badge variant="secondary" className="text-xs shrink-0">{report.language}</Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground line-clamp-2 mb-4">
                        {report.description || 'No description available'}
                      </p>
                      <div className="flex items-center gap-4 text-xs text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Star className="w-3 h-3" /> {report.stars?.toLocaleString() || 0}
                        </span>
                        <span className="flex items-center gap-1">
                          <GitFork className="w-3 h-3" /> {report.forks?.toLocaleString() || 0}
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
