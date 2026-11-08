export type IncidentStatus = "OPEN" | "ACKNOWLEDGED" | "RESOLVED" | "CLOSED";
export type AnalysisStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
export type AutomationStatus = "PENDING" | "RUNNING" | "SUCCESS" | "FAILED";
export type Severity = "UNKNOWN" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type IncidentSource =
  | "MANUAL"
  | "CUSTOM"
  | "PROMETHEUS"
  | "GRAFANA"
  | "GITHUB";

export interface Incident {
  id: number;
  title: string;
  message: string;
  status: IncidentStatus;
  analysis_status: AnalysisStatus;
  automation_status: AutomationStatus;
  severity: Severity | null;
  ai_summary: string | null;
  recommendation: string | null;
  source: IncidentSource;
  fingerprint: string | null;
  target_agent_id: number | null;
  rag_sources: string[] | null;
}

export interface AutomationRule {
  id: number;
  severity: string;
  action_name: string;
  enabled: boolean;
  execution_order: number;
  config: Record<string, unknown>;
}

export interface AutomationRun {
  id: number;
  incident_id: number;
  action_name: string;
  status: string;
  message: string;
  executed_at: string;
}

export interface StatsSummary {
  total: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
}
