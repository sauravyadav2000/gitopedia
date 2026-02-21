import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { Zap, FileText, Star, GitFork, CreditCard, ExternalLink, Clock, ArrowUpRight, ArrowDownLeft } from 'lucide-react';
import { motion } from 'framer-motion';

const API = process.env.REACT_APP_BACKEND_URL;

export default function Dashboard() {
  const { user, profile, getToken, refreshProfile } = useAuth();
  const navigate = useNavigate();
  const [reports, setReports] = useState([]);
  const [transactions, setTransactions] = useState({ payments: [], credits: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) {
      navigate('/auth?redirect=/dashboard');
      return;
    }
    fetchData();
  }, [user]);

  const fetchData = async () => {
    try {
      const token = await getToken();
      const [reportsRes, txRes] = await Promise.all([
        fetch(`${API}/api/user/reports`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API}/api/user/transactions`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (reportsRes.ok) {
        const data = await reportsRes.json();
        setReports(data.reports || []);
      }
      if (txRes.ok) {
        setTransactions(await txRes.json());
      }
    } catch {}
    setLoading(false);
  };

  if (!profile) {
    return (
      <div className="max-w-7xl mx-auto px-6 py-12 space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[1, 2, 3].map(i => <Skeleton key={i} className="h-32" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] px-6 py-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <p className="text-sm text-muted-foreground tracking-widest uppercase font-mono mb-1">Dashboard</p>
          <h1 className="text-3xl md:text-5xl font-heading font-bold tracking-tight">
            Welcome, {profile.display_name || profile.email?.split('@')[0]}
          </h1>
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            <Card className="bg-card/50 backdrop-blur-md border-border/50">
              <CardContent className="p-6">
                <div className="flex items-center justify-between mb-3">
                  <Zap className="w-5 h-5 text-primary" />
                  <Badge variant="outline" className="border-primary/30 text-primary text-xs">Credits</Badge>
                </div>
                <p className="text-4xl font-heading font-bold" data-testid="credit-balance">{profile.credits}</p>
                <p className="text-sm text-muted-foreground mt-1">Available credits</p>
                <Button size="sm" className="mt-4 bg-primary text-primary-foreground hover:bg-primary/90 font-bold rounded-sm w-full"
                  onClick={() => navigate('/credits')} data-testid="buy-credits-button">
                  <CreditCard className="w-4 h-4 mr-1" /> Buy Credits
                </Button>
              </CardContent>
            </Card>
          </motion.div>

          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
            <Card className="bg-card/50 backdrop-blur-md border-border/50">
              <CardContent className="p-6">
                <div className="flex items-center justify-between mb-3">
                  <FileText className="w-5 h-5 text-accent" />
                  <Badge variant="outline" className="border-accent/30 text-accent text-xs">Reports</Badge>
                </div>
                <p className="text-4xl font-heading font-bold" data-testid="report-count">{reports.length}</p>
                <p className="text-sm text-muted-foreground mt-1">Reports generated</p>
                <Button size="sm" variant="outline" className="mt-4 w-full" onClick={() => navigate('/')} data-testid="generate-new-report">
                  Generate New Report
                </Button>
              </CardContent>
            </Card>
          </motion.div>

          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
            <Card className="bg-card/50 backdrop-blur-md border-border/50">
              <CardContent className="p-6">
                <div className="flex items-center justify-between mb-3">
                  <Clock className="w-5 h-5 text-muted-foreground" />
                  <Badge variant="outline" className="text-xs">Account</Badge>
                </div>
                <p className="text-sm font-mono text-foreground truncate" data-testid="user-email">{profile.email}</p>
                <p className="text-sm text-muted-foreground mt-2">
                  Member since {new Date(profile.created_at).toLocaleDateString()}
                </p>
              </CardContent>
            </Card>
          </motion.div>
        </div>

        <Separator className="mb-8" />

        {/* Reports list */}
        <div>
          <h2 className="text-xl font-heading font-semibold mb-4">Your Reports</h2>
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map(i => <Skeleton key={i} className="h-20" />)}
            </div>
          ) : reports.length === 0 ? (
            <div className="text-center py-12 bg-card/30 border border-border/50 rounded-sm" data-testid="no-reports">
              <FileText className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
              <p className="text-muted-foreground">No reports yet</p>
              <p className="text-sm text-muted-foreground mt-1">Generate your first report from the homepage</p>
            </div>
          ) : (
            <div className="space-y-3">
              {reports.map((report, i) => (
                <motion.div key={report.id} initial={{ opacity: 0, x: -5 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.03 }}>
                  <Card
                    className="bg-card/50 border-border/50 hover:border-primary/30 transition-all duration-300 cursor-pointer group"
                    onClick={() => navigate(`/report/${report.id}`)}
                    data-testid={`dashboard-report-${report.id}`}
                  >
                    <CardContent className="p-4 flex items-center justify-between">
                      <div className="min-w-0 flex-1">
                        <h3 className="font-heading font-semibold text-foreground group-hover:text-primary transition-colors truncate">
                          {report.repo_full_name}
                        </h3>
                        <p className="text-sm text-muted-foreground truncate mt-0.5">
                          {report.description || 'No description'}
                        </p>
                      </div>
                      <div className="flex items-center gap-4 ml-4 shrink-0">
                        <div className="hidden sm:flex items-center gap-3 text-xs text-muted-foreground">
                          {report.language && <Badge variant="secondary" className="text-[10px]">{report.language}</Badge>}
                          <span className="flex items-center gap-1"><Star className="w-3 h-3" /> {report.stars?.toLocaleString()}</span>
                          <span className="flex items-center gap-1"><GitFork className="w-3 h-3" /> {report.forks?.toLocaleString()}</span>
                        </div>
                        <ExternalLink className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors" />
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              ))}
            </div>
          )}
        </div>

        <Separator className="my-8" />

        {/* Transaction History */}
        <div>
          <h2 className="text-xl font-heading font-semibold mb-4">Transaction History</h2>
          {(transactions.payments.length === 0 && transactions.credits.length === 0) ? (
            <div className="text-center py-8 bg-card/30 border border-border/50 rounded-sm" data-testid="no-transactions">
              <CreditCard className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
              <p className="text-muted-foreground">No transactions yet</p>
            </div>
          ) : (
            <div className="space-y-2">
              {/* Payment transactions */}
              {transactions.payments.map((tx) => (
                <Card key={tx.id} className="bg-card/50 border-border/50" data-testid={`payment-tx-${tx.id}`}>
                  <CardContent className="p-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-sm flex items-center justify-center ${tx.payment_status === 'paid' ? 'bg-accent/10' : tx.payment_status === 'pending' ? 'bg-yellow-500/10' : 'bg-destructive/10'}`}>
                        <CreditCard className={`w-4 h-4 ${tx.payment_status === 'paid' ? 'text-accent' : tx.payment_status === 'pending' ? 'text-yellow-500' : 'text-destructive'}`} />
                      </div>
                      <div>
                        <p className="text-sm font-medium">
                          Credit Purchase — {tx.package_id} package
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {new Date(tx.created_at).toLocaleString()}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <Badge variant="outline" className={`text-[10px] ${
                        tx.payment_status === 'paid' ? 'border-accent/40 text-accent' :
                        tx.payment_status === 'pending' ? 'border-yellow-500/40 text-yellow-500' :
                        'border-destructive/40 text-destructive'
                      }`}>
                        {tx.payment_status}
                      </Badge>
                      <div className="text-right">
                        <p className="text-sm font-mono font-bold text-foreground">${tx.amount?.toFixed(2)}</p>
                        <p className="text-xs text-accent">+{tx.credits} credits</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}

              {/* Credit transactions */}
              {transactions.credits.map((tx) => (
                <Card key={tx.id} className="bg-card/50 border-border/50" data-testid={`credit-tx-${tx.id}`}>
                  <CardContent className="p-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-sm flex items-center justify-center ${tx.amount > 0 ? 'bg-accent/10' : 'bg-primary/10'}`}>
                        {tx.amount > 0 ? <ArrowDownLeft className="w-4 h-4 text-accent" /> : <ArrowUpRight className="w-4 h-4 text-primary" />}
                      </div>
                      <div>
                        <p className="text-sm font-medium">{tx.description}</p>
                        <p className="text-xs text-muted-foreground">{new Date(tx.created_at).toLocaleString()}</p>
                      </div>
                    </div>
                    <p className={`text-sm font-mono font-bold ${tx.amount > 0 ? 'text-accent' : 'text-primary'}`}>
                      {tx.amount > 0 ? '+' : ''}{tx.amount} credits
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
