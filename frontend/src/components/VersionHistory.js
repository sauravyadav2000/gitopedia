import { useState, useEffect } from 'react';
import { Clock, User, GitCommit, Crown } from 'lucide-react';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDistanceToNow } from 'date-fns';

const API = process.env.REACT_APP_BACKEND_URL;

export default function VersionHistory({ reportId }) {
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchHistory = async () => {
    if (history) return; // Already loaded
    
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/reports/${reportId}/history`);
      if (res.ok) {
        const data = await res.json();
        setHistory(data);
      }
    } catch (error) {
      console.error('Failed to fetch history:', error);
    }
    setLoading(false);
  };

  return (
    <Accordion type="single" collapsible className="border rounded-lg">
      <AccordionItem value="history" className="border-none">
        <AccordionTrigger 
          className="px-4 hover:no-underline"
          onClick={fetchHistory}
        >
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4" />
            <span className="font-semibold">Version History</span>
            {history && (
              <Badge variant="secondary" className="ml-2">
                {history.current_version} versions
              </Badge>
            )}
          </div>
        </AccordionTrigger>
        
        <AccordionContent className="px-4 pb-4">
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map(i => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : history ? (
            <div className="space-y-3">
              {history.history && history.history.length > 0 ? (
                history.history.map((item) => (
                  <div
                    key={item.version}
                    className={`p-3 rounded-lg border ${
                      item.is_current
                        ? 'bg-primary/5 border-primary/30'
                        : 'bg-muted/30 border-muted'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-start gap-3 flex-1">
                        <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
                          item.is_current 
                            ? 'bg-primary/20 text-primary' 
                            : 'bg-muted text-muted-foreground'
                        }`}>
                          {item.is_current ? (
                            <Crown className="w-4 h-4" />
                          ) : (
                            <User className="w-4 h-4" />
                          )}
                        </div>
                        
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <Badge variant={item.is_current ? "default" : "outline"} className="text-xs">
                              v{item.version}
                            </Badge>
                            <span className="text-sm font-medium">
                              {item.owner_name}
                            </span>
                            {item.is_current && (
                              <Badge variant="secondary" className="text-xs">
                                Current
                              </Badge>
                            )}
                          </div>
                          
                          <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                            <div className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              <span>
                                {formatDistanceToNow(new Date(item.generated_at))} ago
                              </span>
                            </div>
                            
                            {item.commit_sha && (
                              <div className="flex items-center gap-1">
                                <GitCommit className="w-3 h-3" />
                                <span className="font-mono">{item.commit_sha}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No version history available
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground text-center py-4">
              Failed to load version history
            </p>
          )}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
