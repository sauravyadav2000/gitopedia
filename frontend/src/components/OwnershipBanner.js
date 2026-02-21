import { User, Clock, GitCommit } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { formatDistanceToNow } from 'date-fns';

export default function OwnershipBanner({ report }) {
  if (!report) return null;

  const daysOld = Math.floor(
    (new Date() - new Date(report.generated_at)) / (1000 * 60 * 60 * 24)
  );

  return (
    <div className="flex items-start gap-4 p-4 bg-gradient-to-r from-primary/5 to-primary/10 border border-primary/20 rounded-lg mb-6">
      <div className="flex-shrink-0 w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center">
        <User className="w-5 h-5 text-primary" />
      </div>
      
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-sm font-medium text-foreground">
            Maintained by{' '}
            <span className="font-bold text-primary">
              {report.current_owner_name || 'Unknown'}
            </span>
          </p>
          <Badge variant="outline" className="text-xs">
            v{report.version || 1}
          </Badge>
        </div>
        
        <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <Clock className="w-3 h-3" />
            <span>
              Updated {formatDistanceToNow(new Date(report.generated_at))} ago
            </span>
          </div>
          
          {report.repo_last_commit_sha && (
            <div className="flex items-center gap-1">
              <GitCommit className="w-3 h-3" />
              <span className="font-mono">
                {report.repo_last_commit_sha.substring(0, 7)}
              </span>
            </div>
          )}
          
          {daysOld > 0 && (
            <Badge 
              variant={daysOld > 30 ? "destructive" : "secondary"} 
              className="text-xs"
            >
              {daysOld} days old
            </Badge>
          )}
        </div>

        {report.previous_owners && report.previous_owners.length > 0 && (
          <p className="text-xs text-muted-foreground mt-1">
            Previously maintained by{' '}
            {report.previous_owners.slice(-2).map(owner => owner.user_name).join(', ')}
            {report.previous_owners.length > 2 && ` and ${report.previous_owners.length - 2} others`}
          </p>
        )}
      </div>
    </div>
  );
}
