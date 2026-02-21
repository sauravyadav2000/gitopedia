import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Building2, Check, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

export default function EnterpriseCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { user, getToken } = useAuth();
  
  const [loading, setLoading] = useState(true);
  const [organizations, setOrganizations] = useState([]);
  const [connecting, setConnecting] = useState(null);
  const [githubToken, setGithubToken] = useState(null);

  useEffect(() => {
    handleCallback();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCallback = async () => {
    const code = searchParams.get('code');
    
    console.log('[EnterpriseCallback] Starting callback handler');
    console.log('[EnterpriseCallback] Code:', code ? `present (${code.length} chars)` : 'MISSING');
    console.log('[EnterpriseCallback] User:', user ? user.uid.substring(0, 8) : 'NOT LOGGED IN');
    
    if (!code) {
      console.error('[EnterpriseCallback] No authorization code in URL');
      toast.error('No authorization code received');
      navigate('/enterprise');
      return;
    }

    if (!user) {
      console.error('[EnterpriseCallback] User not logged in');
      toast.error('Please log in first');
      navigate('/auth?redirect=/enterprise');
      return;
    }

    try {
      console.log('[EnterpriseCallback] Getting Firebase token...');
      const token = await getToken();
      console.log('[EnterpriseCallback] Token received, calling backend...');
      
      // Exchange code for access token
      const res = await fetch(`${API}/api/enterprise/github/callback`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ code })
      });

      console.log('[EnterpriseCallback] Backend response status:', res.status);

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        console.error('[EnterpriseCallback] Backend error:', errorData);
        throw new Error(errorData.detail || 'Failed to authenticate');
      }

      const data = await res.json();
      console.log('[EnterpriseCallback] Success! Organizations:', data.organizations?.length || 0);
      
      setGithubToken(data.access_token);
      setOrganizations(data.organizations || []);
      
      // Show message if no organizations found
      if (!data.organizations || data.organizations.length === 0) {
        if (data.message) {
          toast.warning(data.message);
        } else {
          toast.warning('No organizations found. You need to be a member of at least one GitHub organization.');
        }
      }
      
      setLoading(false);
    } catch (error) {
      console.error('[EnterpriseCallback] Callback error:', error);
      toast.error('Failed to connect GitHub account');
      navigate('/enterprise');
    }
  };

  const handleConnectOrg = async (org) => {
    setConnecting(org.id);
    
    try {
      const token = await getToken();
      
      const res = await fetch(`${API}/api/enterprise/organizations/connect`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          github_org_id: org.id,
          github_org_login: org.login,
          github_org_name: org.name,
          github_token: githubToken,
          avatar_url: org.avatar_url
        })
      });

      if (!res.ok) throw new Error('Failed to connect organization');

      const data = await res.json();
      
      toast.success(`Connected ${org.name || org.login}!`);
      navigate('/enterprise/organizations');
    } catch (error) {
      console.error('Connect error:', error);
      toast.error('Failed to connect organization');
      setConnecting(null);
    }
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-12">
        <Card>
          <CardHeader>
            <Skeleton className="h-8 w-64 mb-2" />
            <Skeleton className="h-4 w-96" />
          </CardHeader>
          <CardContent className="space-y-4">
            {[1, 2, 3].map(i => (
              <Skeleton key={i} className="h-24 w-full" />
            ))}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-heading font-bold mb-2">
          Select Organization
        </h1>
        <p className="text-muted-foreground">
          Choose which organization you'd like to analyze and create a wiki for.
        </p>
      </div>

      {organizations.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Building2 className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-lg font-semibold mb-2">No Organizations Found</h3>
            <p className="text-muted-foreground mb-4">
              You need to be a member of at least one GitHub organization to use Gitopedia Enterprise.
            </p>
            <p className="text-sm text-muted-foreground mb-6">
              Make sure your GitHub account is connected to an organization, or create one at{' '}
              <a 
                href="https://github.com/organizations/new" 
                target="_blank" 
                rel="noopener noreferrer"
                className="text-primary hover:underline"
              >
                github.com/organizations/new
              </a>
            </p>
            <Button
              className="mt-4"
              onClick={() => navigate('/enterprise')}
            >
              Go Back to Enterprise
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {organizations.map(org => (
            <Card
              key={org.id}
              className="hover:border-primary/50 transition-colors cursor-pointer"
              onClick={() => !connecting && handleConnectOrg(org)}
            >
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    {org.avatar_url && (
                      <img
                        src={org.avatar_url}
                        alt={org.login}
                        className="w-12 h-12 rounded-lg"
                      />
                    )}
                    <div>
                      <h3 className="font-semibold text-lg">{org.name || org.login}</h3>
                      <p className="text-sm text-muted-foreground">@{org.login}</p>
                    </div>
                  </div>

                  <Button
                    disabled={connecting === org.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleConnectOrg(org);
                    }}
                  >
                    {connecting === org.id ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Connecting...
                      </>
                    ) : (
                      <>
                        <Check className="w-4 h-4 mr-2" />
                        Connect
                      </>
                    )}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
