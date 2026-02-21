import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Building2, GitBranch, Users, Zap, Shield, Clock, ArrowRight, Check } from 'lucide-react';
import { motion } from 'framer-motion';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

export default function EnterpriseLanding() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [connecting, setConnecting] = useState(false);

  const handleConnectGitHub = async () => {
    if (!user) {
      navigate('/auth?redirect=/enterprise');
      return;
    }

    setConnecting(true);
    try {
      // Get GitHub OAuth URL
      const res = await fetch(`${API}/api/enterprise/github/authorize`);
      const data = await res.json();
      
      // Redirect to GitHub OAuth
      window.location.href = data.url;
    } catch (error) {
      console.error('OAuth error:', error);
      toast.error('Failed to connect to GitHub');
      setConnecting(false);
    }
  };

  const features = [
    {
      icon: GitBranch,
      title: "Bulk Repository Analysis",
      description: "Analyze all repositories in your organization at once. Generate comprehensive reports for every repo automatically."
    },
    {
      icon: Users,
      title: "Team Collaboration",
      description: "Share organization wikis with your team. Token-based access control makes sharing easy and secure."
    },
    {
      icon: Zap,
      title: "Background Processing",
      description: "Long-running analysis happens in the background. Get notified when your organization wiki is ready."
    },
    {
      icon: Shield,
      title: "Private & Secure",
      description: "Your organization data is secure. Wiki access is controlled via unique tokens that you can regenerate anytime."
    }
  ];

  const pricingTiers = [
    {
      name: "Small Teams",
      price: "$50",
      repos: "0-50 repositories",
      features: [
        "Full repository analysis",
        "Organization overview",
        "Tech stack summary",
        "Shareable wiki",
        "One-time payment"
      ]
    },
    {
      name: "Medium Teams",
      price: "$100",
      repos: "50-100 repositories",
      features: [
        "Everything in Small",
        "Cross-repo analysis",
        "Architecture diagrams",
        "Priority processing",
        "One-time payment"
      ],
      popular: true
    },
    {
      name: "Large Teams",
      price: "$200",
      repos: "100+ repositories",
      features: [
        "Everything in Medium",
        "Unlimited repositories",
        "Advanced analytics",
        "Dedicated support",
        "One-time payment"
      ]
    }
  ];

  return (
    <div className="min-h-screen">
      {/* Hero Section */}
      <section className="relative overflow-hidden bg-gradient-to-br from-primary/10 via-background to-background py-20 px-6">
        <div className="max-w-6xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-center"
          >
            <Badge variant="secondary" className="mb-4">
              <Building2 className="w-3 h-3 mr-1" />
              Gitopedia Enterprise
            </Badge>
            
            <h1 className="text-4xl md:text-6xl font-heading font-bold tracking-tight mb-6">
              Analyze Your Entire
              <span className="text-primary"> Organization</span>
            </h1>
            
            <p className="text-xl text-muted-foreground max-w-2xl mx-auto mb-8">
              Generate comprehensive wikis for all repositories in your GitHub organization.
              One payment, complete analysis, shareable knowledge base.
            </p>
            
            <div className="flex items-center justify-center gap-4">
              <Button
                size="lg"
                onClick={handleConnectGitHub}
                disabled={connecting}
                className="gap-2"
              >
                {connecting ? (
                  <>
                    <Clock className="w-5 h-5 animate-spin" />
                    Connecting...
                  </>
                ) : (
                  <>
                    Connect GitHub Organization
                    <ArrowRight className="w-5 h-5" />
                  </>
                )}
              </Button>
              
              {user && (
                <Button
                  size="lg"
                  variant="outline"
                  onClick={() => navigate('/enterprise/organizations')}
                >
                  View My Organizations
                </Button>
              )}
            </div>
          </motion.div>
        </div>
      </section>

      {/* Features */}
      <section className="py-20 px-6 bg-muted/30">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-heading font-bold mb-4">
              Why Choose Enterprise?
            </h2>
            <p className="text-muted-foreground max-w-2xl mx-auto">
              Scale your repository intelligence across your entire organization
            </p>
          </div>

          <div className="grid md:grid-cols-2 gap-6">
            {features.map((feature, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.1 }}
                viewport={{ once: true }}
              >
                <Card className="h-full">
                  <CardHeader>
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                        <feature.icon className="w-5 h-5 text-primary" />
                      </div>
                      <CardTitle>{feature.title}</CardTitle>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <CardDescription>{feature.description}</CardDescription>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="py-20 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-heading font-bold mb-4">
              Simple, Transparent Pricing
            </h2>
            <p className="text-muted-foreground">
              One-time payment based on your organization size. No subscriptions.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-6">
            {pricingTiers.map((tier, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.1 }}
                viewport={{ once: true }}
              >
                <Card className={`relative h-full ${tier.popular ? 'border-primary shadow-lg' : ''}`}>
                  {tier.popular && (
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                      <Badge className="bg-primary">Most Popular</Badge>
                    </div>
                  )}
                  
                  <CardHeader>
                    <CardTitle>{tier.name}</CardTitle>
                    <CardDescription className="text-sm">{tier.repos}</CardDescription>
                    <div className="mt-4">
                      <span className="text-4xl font-bold">{tier.price}</span>
                      <span className="text-muted-foreground ml-2">one-time</span>
                    </div>
                  </CardHeader>
                  
                  <CardContent>
                    <ul className="space-y-3">
                      {tier.features.map((feature, j) => (
                        <li key={j} className="flex items-start gap-2">
                          <Check className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                          <span className="text-sm">{feature}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-20 px-6 bg-primary/5">
        <div className="max-w-4xl mx-auto text-center">
          <h2 className="text-3xl font-heading font-bold mb-4">
            Ready to Get Started?
          </h2>
          <p className="text-muted-foreground mb-8">
            Connect your GitHub organization and get a comprehensive wiki in minutes.
          </p>
          <Button size="lg" onClick={handleConnectGitHub} disabled={connecting}>
            {connecting ? 'Connecting...' : 'Connect GitHub Organization'}
          </Button>
        </div>
      </section>
    </div>
  );
}
