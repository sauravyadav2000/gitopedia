import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Zap, Check, Loader2, ArrowLeft, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import { motion } from 'framer-motion';

const API = process.env.REACT_APP_BACKEND_URL;

const PACKAGES = [
  { id: 'starter', credits: 5, price: '$2', perCredit: '$0.40', tag: null },
  { id: 'popular', credits: 15, price: '$5', perCredit: '$0.33', tag: 'Best Value' },
  { id: 'pro', credits: 35, price: '$10', perCredit: '$0.29', tag: 'Most Credits' },
];

export default function Credits() {
  const { user, profile, getToken, refreshProfile } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionId = searchParams.get('session_id');
  const [purchasing, setPurchasing] = useState('');
  const [verifying, setVerifying] = useState(false);
  const [paymentSuccess, setPaymentSuccess] = useState(false);
  const polledRef = useRef(false);

  useEffect(() => {
    if (!user) {
      navigate('/auth?redirect=/credits');
      return;
    }
  }, [user]);

  const pollPaymentStatus = useCallback(async (sid, attempts = 0) => {
    if (attempts >= 8) {
      setVerifying(false);
      toast.error('Payment verification timed out. Contact support if you were charged.');
      setSearchParams({}, { replace: true });
      return;
    }
    try {
      const token = await getToken();
      const res = await fetch(`${API}/api/credits/checkout/status/${sid}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error();
      const data = await res.json();
      if (data.payment_status === 'paid') {
        setVerifying(false);
        setPaymentSuccess(true);
        refreshProfile();
        toast.success('Credits added successfully!');
        setSearchParams({}, { replace: true });
        return;
      }
      if (data.status === 'expired') {
        setVerifying(false);
        toast.error('Payment session expired.');
        setSearchParams({}, { replace: true });
        return;
      }
      setTimeout(() => pollPaymentStatus(sid, attempts + 1), 2000);
    } catch {
      setTimeout(() => pollPaymentStatus(sid, attempts + 1), 2000);
    }
  }, [getToken, refreshProfile, setSearchParams]);

  useEffect(() => {
    if (sessionId && user && !polledRef.current) {
      polledRef.current = true;
      setVerifying(true);
      pollPaymentStatus(sessionId);
    }
  }, [sessionId, user, pollPaymentStatus]);

  const handlePurchase = async (packageId) => {
    setPurchasing(packageId);
    try {
      const token = await getToken();
      const res = await fetch(`${API}/api/credits/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ package_id: packageId, origin_url: window.location.origin }),
      });
      if (!res.ok) {
        const err = await res.json();
        toast.error(err.detail || 'Failed to create checkout session');
        setPurchasing('');
        return;
      }
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      }
    } catch {
      toast.error('Payment error');
      setPurchasing('');
    }
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] px-6 py-8">
      <div className="max-w-4xl mx-auto">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)} className="text-muted-foreground mb-6" data-testid="back-button">
          <ArrowLeft className="w-4 h-4 mr-1" /> Back
        </Button>

        {/* Verification state */}
        {verifying && (
          <Card className="mb-8 border-primary/30 bg-primary/5" data-testid="verifying-payment">
            <CardContent className="p-6 flex items-center gap-4">
              <Loader2 className="w-6 h-6 text-primary animate-spin" />
              <div>
                <p className="font-heading font-semibold">Verifying payment...</p>
                <p className="text-sm text-muted-foreground">Please wait while we confirm your purchase.</p>
              </div>
            </CardContent>
          </Card>
        )}

        {paymentSuccess && (
          <Card className="mb-8 border-accent/30 bg-accent/5" data-testid="payment-success">
            <CardContent className="p-6 flex items-center gap-4">
              <CheckCircle2 className="w-6 h-6 text-accent" />
              <div>
                <p className="font-heading font-semibold">Payment successful!</p>
                <p className="text-sm text-muted-foreground">Your credits have been added to your account.</p>
              </div>
            </CardContent>
          </Card>
        )}

        <div className="mb-8">
          <p className="text-sm text-muted-foreground tracking-widest uppercase font-mono mb-1">Credits</p>
          <h1 className="text-3xl md:text-5xl font-heading font-bold tracking-tight">Buy Credits</h1>
          <p className="text-base text-muted-foreground mt-2">
            Credits let you generate and edit reports. Current balance:{' '}
            <span className="text-primary font-mono font-bold">{profile?.credits || 0}</span>
          </p>
        </div>

        {/* Pricing info */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8 text-sm text-muted-foreground">
          <div className="flex items-center gap-2 bg-muted/30 p-3 rounded-sm">
            <Zap className="w-4 h-4 text-primary" /> Generate report: 2 credits
          </div>
          <div className="flex items-center gap-2 bg-muted/30 p-3 rounded-sm">
            <Zap className="w-4 h-4 text-primary" /> Edit & republish: 1 credit
          </div>
          <div className="flex items-center gap-2 bg-muted/30 p-3 rounded-sm">
            <Check className="w-4 h-4 text-accent" /> Read reports: Always free
          </div>
        </div>

        {/* Pricing cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {PACKAGES.map((pkg, i) => (
            <motion.div
              key={pkg.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
            >
              <Card
                className={`bg-card/50 backdrop-blur-md border-border/50 relative overflow-hidden ${
                  pkg.tag === 'Best Value' ? 'border-primary/50 shadow-[0_0_20px_rgba(217,70,239,0.15)]' : ''
                }`}
                data-testid={`credit-package-${pkg.id}`}
              >
                {pkg.tag && (
                  <div className="absolute top-0 right-0">
                    <Badge className="rounded-none rounded-bl-sm bg-primary text-primary-foreground text-[10px] font-bold">
                      {pkg.tag}
                    </Badge>
                  </div>
                )}
                <CardContent className="p-6 text-center">
                  <p className="text-4xl font-heading font-bold mt-2">{pkg.credits}</p>
                  <p className="text-sm text-muted-foreground mb-4">credits</p>
                  <p className="text-2xl font-heading font-bold text-foreground">{pkg.price}</p>
                  <p className="text-xs text-muted-foreground mt-1 mb-6">{pkg.perCredit} per credit</p>
                  <Button
                    className={`w-full font-bold tracking-wide rounded-sm ${
                      pkg.tag === 'Best Value'
                        ? 'bg-primary text-primary-foreground hover:bg-primary/90'
                        : 'bg-secondary text-secondary-foreground hover:bg-secondary/80'
                    }`}
                    onClick={() => handlePurchase(pkg.id)}
                    disabled={!!purchasing}
                    data-testid={`purchase-${pkg.id}`}
                  >
                    {purchasing === pkg.id ? (
                      <><Loader2 className="w-4 h-4 mr-1 animate-spin" /> Processing...</>
                    ) : (
                      `Buy for ${pkg.price}`
                    )}
                  </Button>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}
