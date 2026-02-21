import { AlertCircle, ArrowUpCircle, GitCommit, Calendar } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

export default function UpgradeAlert({ 
  canUpgrade, 
  upgradeReason, 
  daysOld, 
  newCommitsCount,
  onUpgrade,
  isUpgrading 
}) {
  if (!canUpgrade) return null;

  return (
    <Alert variant="warning" className="mb-6 border-orange-500/50 bg-orange-50 dark:bg-orange-950/20">
      <AlertCircle className="h-5 w-5 text-orange-600" />
      <AlertTitle className="text-orange-900 dark:text-orange-100 font-bold">
        This report is outdated
      </AlertTitle>
      <AlertDescription className="mt-2">
        <div className="space-y-3">
          <p className="text-sm text-orange-800 dark:text-orange-200">
            {upgradeReason || 'This report can be upgraded with the latest repository data.'}
          </p>
          
          <div className="flex items-center gap-4 text-xs text-orange-700 dark:text-orange-300">
            {daysOld > 0 && (
              <div className="flex items-center gap-1">
                <Calendar className="w-4 h-4" />
                <span className="font-medium">{daysOld} days old</span>
              </div>
            )}
            
            {newCommitsCount > 0 && (
              <div className="flex items-center gap-1">
                <GitCommit className="w-4 h-4" />
                <span className="font-medium">{newCommitsCount} new commits</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3 pt-2">
            <Button 
              onClick={onUpgrade} 
              disabled={isUpgrading}
              className="bg-orange-600 hover:bg-orange-700 text-white"
              size="sm"
            >
              {isUpgrading ? (
                <>
                  <ArrowUpCircle className="w-4 h-4 mr-2 animate-spin" />
                  Upgrading...
                </>
              ) : (
                <>
                  <ArrowUpCircle className="w-4 h-4 mr-2" />
                  Upgrade Report (2 credits)
                </>
              )}
            </Button>
            
            <p className="text-xs text-orange-600 dark:text-orange-400">
              You'll become the new maintainer of this report
            </p>
          </div>
        </div>
      </AlertDescription>
    </Alert>
  );
}
