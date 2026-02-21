import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Zap, User, LogOut, BookOpen, CreditCard, LayoutDashboard, Building2 } from 'lucide-react';

export default function Header() {
  const { user, profile, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/');
  };

  return (
    <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-xl no-print">
      <div className="max-w-7xl mx-auto flex items-center justify-between h-16 px-6">
        <Link to="/" className="flex items-center gap-2.5 group" data-testid="logo-link">
          <div className="w-8 h-8 rounded-sm bg-primary flex items-center justify-center">
            <BookOpen className="w-4 h-4 text-primary-foreground" />
          </div>
          <span className="font-heading text-xl font-bold tracking-tight text-foreground group-hover:text-primary transition-colors duration-300">
            Gitopedia
          </span>
        </Link>

        <nav className="hidden md:flex items-center gap-6">
          <Link
            to="/browse"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors duration-200"
            data-testid="nav-browse"
          >
            Browse Reports
          </Link>
          <Link
            to="/enterprise"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors duration-200 flex items-center gap-1"
            data-testid="nav-enterprise"
          >
            <Building2 className="w-3.5 h-3.5" />
            Enterprise
          </Link>
          {user && (
            <Link
              to="/dashboard"
              className="text-sm text-muted-foreground hover:text-foreground transition-colors duration-200"
              data-testid="nav-dashboard"
            >
              Dashboard
            </Link>
          )}
        </nav>

        <div className="flex items-center gap-3">
          {user && profile && (
            <Link to="/credits" data-testid="credit-badge">
              <Badge
                variant="outline"
                className="cursor-pointer border-primary/40 bg-primary/5 hover:bg-primary/10 transition-all duration-300 px-3 py-1.5 gap-1.5"
              >
                <Zap className="w-3.5 h-3.5 text-primary" />
                <span className="text-sm font-mono font-bold text-primary">{profile.credits}</span>
                <span className="text-xs text-muted-foreground">credits</span>
              </Badge>
            </Link>
          )}

          {user ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="gap-2 text-muted-foreground" data-testid="user-menu-trigger">
                  <User className="w-4 h-4" />
                  <span className="hidden sm:inline text-sm">{profile?.display_name || profile?.email?.split('@')[0]}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48 bg-card border-border">
                <DropdownMenuItem onClick={() => navigate('/dashboard')} data-testid="menu-dashboard">
                  <LayoutDashboard className="w-4 h-4 mr-2" /> Dashboard
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => navigate('/credits')} data-testid="menu-credits">
                  <CreditCard className="w-4 h-4 mr-2" /> Buy Credits
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => navigate('/enterprise/organizations')} data-testid="menu-enterprise">
                  <Building2 className="w-4 h-4 mr-2" /> My Organizations
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleLogout} data-testid="menu-logout">
                  <LogOut className="w-4 h-4 mr-2" /> Log Out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => navigate('/auth')}
                className="text-muted-foreground"
                data-testid="login-button"
              >
                Log In
              </Button>
              <Button
                size="sm"
                onClick={() => navigate('/auth?mode=signup')}
                className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-sm font-bold tracking-wide"
                data-testid="signup-button"
              >
                Sign Up
              </Button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
