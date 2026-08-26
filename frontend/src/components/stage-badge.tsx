import { Badge } from "@/components/ui/badge";
import { STAGE_LABELS, type ProspectStage } from "@/lib/types/crm";
import { cn } from "@/lib/utils";

const STAGE_STYLES: Record<ProspectStage, string> = {
  targeted: "bg-muted text-muted-foreground",
  visited: "bg-secondary text-secondary-foreground",
  requirement_collected: "bg-accent text-accent-foreground",
  sample_provided: "bg-chart-2/25 text-primary",
  quotation_sent: "bg-primary/15 text-primary",
  negotiation: "bg-warning/20 text-warning-foreground",
  lost: "bg-destructive/15 text-destructive",
  deferred: "bg-muted text-muted-foreground line-through",
  won: "bg-primary text-primary-foreground",
};

export function StageBadge({ stage }: { stage: ProspectStage }) {
  return (
    <Badge className={cn("border-transparent", STAGE_STYLES[stage])}>
      {STAGE_LABELS[stage]}
    </Badge>
  );
}
