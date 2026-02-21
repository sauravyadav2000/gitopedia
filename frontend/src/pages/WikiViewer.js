import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import StreamingMarkdown from '@/components/StreamingMarkdown';
import { Building2, ExternalLink, Share2, GitBranch, Code2 } from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

export default function WikiViewer() {
  const { orgLogin, token } = useParams();
  const [wiki, setWiki] = useState(null);
  const [organization, setOrganization] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchWiki();
  }, [orgLogin, token]);

  const fetchWiki = async () => {
    try {
      const res = await fetch(`${API}/api/wiki/${orgLogin}/${token}`);
      
      if (!res.ok) {
        if (res.status === 404) {
          setError('Wiki not found or invalid access token');
        } else {
          setError('Failed to load wiki');
        }
        setLoading(false);
        return;
      }

      const data = await res.json();
      setWiki(data.wiki);
      setOrganization(data.organization);
    } catch (error) {
      console.error('Fetch wiki error:', error);
      setError('Failed to load wiki');
    }
    setLoading(false);
  };

  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href);
    toast.success('Wiki link copied to clipboard!');
  };

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto px-6 py-12">
        <Skeleton className="h-16 w-96 mb-8" />
        <div className="grid md:grid-cols-4 gap-6">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
        <Skeleton className="h-96 mt-8" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-12">
        <Card className="border-destructive">
          <CardContent className="py-12 text-center">
            <Building2 className="w-16 h-16 text-destructive mx-auto mb-4 opacity-50" />
            <h3 className="text-lg font-semibold mb-2 text-destructive">{error}</h3>
            <p className="text-muted-foreground">
              Please check the URL or contact the organization owner.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!wiki || !organization) return null;

  const topLanguages = Object.entries(wiki.tech_stack_summary || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);

  return (
    <div className="min-h-screen bg-gradient-to-b from-background to-muted/20">
      {/* Header */}
      <div className="border-b bg-card/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-6">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4">
              {organization.avatar_url && (
                <img
                  src={organization.avatar_url}
                  alt={organization.name}
                  className="w-16 h-16 rounded-lg border"
                />
              )}
              <div>
                <h1 className="text-3xl font-heading font-bold mb-1">
                  {organization.name}
                </h1>
                <p className="text-muted-foreground flex items-center gap-2">
                  <GitBranch className="w-4 h-4" />
                  {organization.analyzed_repos} of {organization.total_repos} repositories analyzed
                </p>
              </div>
            </div>

            <Button onClick={handleShare} variant="outline" className="gap-2">
              <Share2 className="w-4 h-4" />
              Share Wiki
            </Button>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-12">
        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <Card>
            <CardContent className="pt-6">
              <div className="text-3xl font-bold mb-1">{organization.total_repos}</div>
              <div className="text-sm text-muted-foreground">Total Repositories</div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <div className="text-3xl font-bold mb-1">{organization.analyzed_repos}</div>
              <div className="text-sm text-muted-foreground">Analyzed</div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <div className="text-3xl font-bold mb-1">{Object.keys(wiki.tech_stack_summary || {}).length}</div>
              <div className="text-sm text-muted-foreground">Languages</div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <div className="text-3xl font-bold mb-1">{wiki.repo_reports?.length || 0}</div>
              <div className="text-sm text-muted-foreground">Reports Generated</div>
            </CardContent>
          </Card>
        </div>

        {/* Tech Stack */}
        {topLanguages.length > 0 && (
          <Card className="mb-8">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Code2 className="w-5 h-5" />
                Technology Stack
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {topLanguages.map(([lang, count]) => (
                  <Badge key={lang} variant="secondary" className="text-sm px-3 py-1">
                    {lang} ({count})
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Wiki Content */}
        <Card>
          <CardHeader>
            <CardTitle>Organization Overview</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="prose prose-slate dark:prose-invert max-w-none">
              <StreamingMarkdown content={wiki.overview_content} isStreaming={false} />
            </div>
          </CardContent>
        </Card>

        {/* Repository Reports */}
        {wiki.repo_reports && wiki.repo_reports.length > 0 && (
          <Card className="mt-8">
            <CardHeader>
              <CardTitle>Repository Reports</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {wiki.repo_reports.map((report, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between p-3 rounded-lg border hover:border-primary/50 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <GitBranch className="w-4 h-4 text-muted-foreground" />
                      <span className="font-medium">{report.repo_name}</span>
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => window.open(`/report/${report.report_id}`, '_blank')}
                    >
                      <ExternalLink className="w-4 h-4" />
                    </Button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Footer */}
        <div className="mt-12 text-center text-sm text-muted-foreground">
          <p>
            Generated by{' '}
            <a href="/" className="text-primary hover:underline">
              Gitopedia
            </a>
            {' '}•{' '}
            Last updated {new Date(wiki.last_updated_at).toLocaleDateString()}
          </p>
        </div>
      </div>
    </div>
  );
}
