import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Progress } from '@/components/ui/progress';
import { Building2, Plus, ExternalLink, Loader2, CheckCircle, Clock, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

export default function OrganizationsList() {
  const { user, getToken } = useAuth();
  const navigate = useNavigate();
  const [organizations, setOrganizations] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (user) {
      fetchOrganizations();
    }
  }, [user]);

  const fetchOrganizations = async () => {
    try {
      const token = await getToken();
      const res = await fetch(`${API}/api/enterprise/organizations`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });

      if (!res.ok) throw new Error('Failed to fetch organizations');

      const data = await res.json();
      setOrganizations(data.organizations);
    } catch (error) {
      console.error('Fetch error:', error);
      toast.error('Failed to load organizations');
    }
    setLoading(false);
  };

  const handleConnectNew = async () => {
    try {
      const token = await getToken();
      const res = await fetch(`${API}/api/enterprise/github/authorize`);
      const data = await res.json();
      window.location.href = data.url;
    } catch (error) {
      toast.error('Failed to start GitHub connection');
    }
  };

  const getStatusBadge = (org) => {
    if (org.payment_status === 'pending') {
      return <Badge variant="secondary"><Clock className="w-3 h-3 mr-1" />Pending Payment</Badge>;
    }
    if (!org.wiki_id) {
      return <Badge variant="secondary"><Clock className="w-3 h-3 mr-1" />Not Analyzed</Badge>;
    }
    return <Badge variant="default"><CheckCircle className="w-3 h-3 mr-1" />Complete</Badge>;
  };

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto px-6 py-12">
        <div className="flex justify-between items-center mb-8">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-10 w-48" />
        </div>
        <div className="grid md:grid-cols-2 gap-6">
          {[1, 2].map(i => (
            <Skeleton key={i} className="h-48" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-12">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-heading font-bold mb-2">
            My Organizations
          </h1>
          <p className="text-muted-foreground">
            Manage and analyze your GitHub organizations
          </p>
        </div>

        <Button onClick={handleConnectNew} className="gap-2">
          <Plus className="w-4 h-4" />
          Connect Organization
        </Button>
      </div>

      {organizations.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="py-12 text-center">
            <Building2 className="w-16 h-16 text-muted-foreground mx-auto mb-4 opacity-50" />
            <h3 className="text-lg font-semibold mb-2">No organizations connected</h3>
            <p className="text-muted-foreground mb-6 max-w-sm mx-auto">
              Connect your first GitHub organization to start generating comprehensive wikis.
            </p>
            <Button onClick={handleConnectNew}>
              <Plus className="w-4 h-4 mr-2" />
              Connect Your First Organization
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid md:grid-cols-2 gap-6">
          {organizations.map(org => (
            <Card
              key={org.id}
              className="hover:border-primary/50 transition-all cursor-pointer"
              onClick={() => navigate(`/enterprise/organizations/${org.id}`)}
            >
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    {org.avatar_url && (
                      <img
                        src={org.avatar_url}
                        alt={org.github_org_name}
                        className="w-12 h-12 rounded-lg"
                      />
                    )}
                    <div>
                      <CardTitle>{org.github_org_name}</CardTitle>
                      <CardDescription>@{org.github_org_login}</CardDescription>
                    </div>
                  </div>
                  {getStatusBadge(org)}
                </div>
              </CardHeader>

              <CardContent>
                <div className="space-y-4">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Total Repositories</span>
                    <span className="font-semibold">{org.total_repos}</span>
                  </div>

                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Analyzed</span>
                    <span className="font-semibold">{org.analyzed_repos || 0}</span>
                  </div>

                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Pricing Tier</span>
                    <Badge variant="outline">{org.pricing_tier}</Badge>
                  </div>

                  {org.analyzed_repos > 0 && org.total_repos > 0 && (
                    <div className="space-y-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">Progress</span>
                        <span className="font-medium">
                          {Math.round((org.analyzed_repos / org.total_repos) * 100)}%
                        </span>
                      </div>
                      <Progress
                        value={(org.analyzed_repos / org.total_repos) * 100}
                        className="h-2"
                      />
                    </div>
                  )}

                  <div className="pt-2 flex gap-2">
                    {org.wiki_id ? (
                      <Button
                        size="sm"
                        className="flex-1"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(org.wiki_url);
                        }}
                      >
                        <ExternalLink className="w-4 h-4 mr-2" />
                        View Wiki
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        className="flex-1"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/enterprise/organizations/${org.id}`);
                        }}
                      >
                        {org.payment_status === 'pending' ? 'Complete Payment' : 'Start Analysis'}
                      </Button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
