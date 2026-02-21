import { useState, useEffect } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { 
  ArrowLeft, ExternalLink, Loader2, CheckCircle, Clock, 
  GitBranch, Package, DollarSign, RefreshCw 
} from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

export default function OrganizationDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { user, getToken } = useAuth();
  
  const [organization, setOrganization] = useState(null);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (user) {
      fetchOrganization();
    }
  }, [id, user]);

  useEffect(() => {
    // Check for payment success
    const paymentStatus = searchParams.get('payment');
    if (paymentStatus === 'success') {
      toast.success('Payment successful! Starting analysis...');
      setTimeout(() => handleStartAnalysis(), 2000);
    }
  }, [searchParams]);

  useEffect(() => {
    // Poll for job updates if analysis is running
    if (job && (job.status === 'queued' || job.status === 'processing')) {
      const interval = setInterval(fetchOrganization, 5000); // Poll every 5 seconds
      return () => clearInterval(interval);
    }
  }, [job]);

  const fetchOrganization = async () => {
    try {
      const token = await getToken();
      const res = await fetch(`${API}/api/enterprise/organizations/${id}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });

      if (!res.ok) throw new Error('Failed to fetch organization');

      const data = await res.json();
      setOrganization(data.organization);
      setJob(data.active_job);
    } catch (error) {
      console.error('Fetch error:', error);
      toast.error('Failed to load organization');
      navigate('/enterprise/organizations');
    }
    setLoading(false);
  };

  const handleStartAnalysis = async () => {
    setStarting(true);
    try {
      const token = await getToken();
      const res = await fetch(`${API}/api/enterprise/organizations/${id}/analyze`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });

      if (!res.ok) throw new Error('Failed to start analysis');

      const data = await res.json();
      
      if (data.requires_payment) {
        // Redirect to Stripe checkout
        window.location.href = data.checkout_url;
      } else {
        toast.success('Analysis started!');
        setJob(data.job || { status: 'queued' });
        fetchOrganization();
      }
    } catch (error) {
      console.error('Start analysis error:', error);
      toast.error('Failed to start analysis');
    }
    setStarting(false);
  };

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto px-6 py-12">
        <Skeleton className="h-10 w-64 mb-8" />
        <div className="grid md:grid-cols-3 gap-6">
          <Skeleton className="h-48 md:col-span-2" />
          <Skeleton className="h-48" />
        </div>
      </div>
    );
  }

  if (!organization) return null;

  return (
    <div className="max-w-6xl mx-auto px-6 py-12">
      {/* Header */}
      <div className="mb-8">
        <Button
          variant="ghost"
          size="sm"
          className="mb-4"
          onClick={() => navigate('/enterprise/organizations')}
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back to Organizations
        </Button>

        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            {organization.avatar_url && (
              <img
                src={organization.avatar_url}
                alt={organization.github_org_name}
                className="w-16 h-16 rounded-lg"
              />
            )}
            <div>
              <h1 className="text-3xl font-heading font-bold mb-1">
                {organization.github_org_name}
              </h1>
              <p className="text-muted-foreground">@{organization.github_org_login}</p>
            </div>
          </div>

          {organization.wiki_url && (
            <Button onClick={() => window.open(organization.wiki_url, '_blank')}>
              <ExternalLink className="w-4 h-4 mr-2" />
              View Wiki
            </Button>
          )}
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        {/* Main Content */}
        <div className="md:col-span-2 space-y-6">
          {/* Analysis Status */}
          {job ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  {job.status === 'processing' && <Loader2 className="w-5 h-5 animate-spin text-primary" />}
                  {job.status === 'completed' && <CheckCircle className="w-5 h-5 text-green-500" />}
                  {job.status === 'queued' && <Clock className="w-5 h-5 text-orange-500" />}
                  Analysis {job.status === 'completed' ? 'Complete' : 'In Progress'}
                </CardTitle>
                <CardDescription>
                  {job.status === 'processing' && 'Analyzing repositories and generating wiki...'}
                  {job.status === 'queued' && 'Analysis queued and will start soon...'}
                  {job.status === 'completed' && 'All repositories have been analyzed!'}
                </CardDescription>
              </CardHeader>

              <CardContent className="space-y-4">
                {job.total_repos > 0 && (
                  <>
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Progress</span>
                      <span className="font-medium">
                        {job.processed_repos} / {job.total_repos} repos ({Math.round(job.progress_percentage)}%)
                      </span>
                    </div>
                    <Progress value={job.progress_percentage} className="h-3" />
                  </>
                )}

                {job.status === 'processing' && job.total_repos > 0 && (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Processing repositories...</span>
                  </div>
                )}

                {job.status === 'completed' && (
                  <div className="flex flex-col gap-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Successfully analyzed</span>
                      <span className="font-medium text-green-600">{job.generated_reports?.length || 0} repos</span>
                    </div>
                    {job.failed_repo_names && job.failed_repo_names.length > 0 && (
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">Failed</span>
                        <span className="font-medium text-red-600">{job.failed_repo_names.length} repos</span>
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          ) : (
            <Card className="border-dashed">
              <CardContent className="py-12 text-center">
                <GitBranch className="w-12 h-12 text-muted-foreground mx-auto mb-4 opacity-50" />
                <h3 className="text-lg font-semibold mb-2">Ready to Analyze</h3>
                <p className="text-muted-foreground mb-6 max-w-md mx-auto">
                  Start analyzing all {organization.total_repos} repositories in this organization to generate a comprehensive wiki.
                </p>
                <Button
                  onClick={handleStartAnalysis}
                  disabled={starting}
                  size="lg"
                >
                  {starting ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Starting...
                    </>
                  ) : (
                    'Start Analysis'
                  )}
                </Button>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Info Card */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Organization Info</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Total Repos</span>
                <Badge variant="secondary">{organization.total_repos}</Badge>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Analyzed</span>
                <Badge variant="secondary">{organization.analyzed_repos || 0}</Badge>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Pricing Tier</span>
                <Badge>{organization.pricing_tier}</Badge>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Payment</span>
                <Badge variant={organization.payment_status === 'paid' ? 'default' : 'secondary'}>
                  {organization.payment_status}
                </Badge>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Amount</span>
                <span className="font-semibold">${organization.paid_amount}</span>
              </div>
            </CardContent>
          </Card>

          {/* Actions */}
          {organization.wiki_url && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Quick Actions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Button
                  variant="outline"
                  className="w-full justify-start"
                  onClick={() => window.open(organization.wiki_url, '_blank')}
                >
                  <ExternalLink className="w-4 h-4 mr-2" />
                  View Wiki
                </Button>
                <Button
                  variant="outline"
                  className="w-full justify-start"
                  onClick={() => {
                    navigator.clipboard.writeText(window.location.origin + organization.wiki_url);
                    toast.success('Wiki link copied!');
                  }}
                >
                  <Package className="w-4 h-4 mr-2" />
                  Copy Wiki Link
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
