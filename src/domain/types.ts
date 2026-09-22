export type WorkflowStatus = 'RUNNING' | 'WAITING' | 'COMPLETED' | 'FAILED' | 'OFFLINE_PAUSED' | 'QUEUED_OFFLINE'
export type ReservationType = 'HARD' | 'SOFT' | 'NONE'
export type ReservationStatus = 'ACTIVE' | 'EXPIRING' | 'RELEASED'
export type ResourceType = 'Model tokens' | 'API quota' | 'Concurrency' | 'Database'
export type PolicyMode = 'Light' | 'Medium' | 'Aggressive'
export type EventType = 'success' | 'info' | 'warning' | 'danger'

export interface Workflow {
  id: string; name: string; agentType: string; status: WorkflowStatus; progress: number; workAtRisk: number
  currentStep: string; predictionConfidence: number; reservationType: ReservationType; resourceNeed: string; updatedAt: string
  tokensSpent?: string; remainingDemand?: string; protectionValue?: number; waitingTime?: string; completedSteps?: string[]
  timeline?: Array<{ label: string; detail: string; state: 'complete' | 'current' | 'queued' }>; recentEventIds?: string[]
}
export interface Resource {
  id: string; name: string; type: ResourceType; capacity: string; used: number; reserved: number; available: number; unit: string; trend: number
  rateLimit?: string; currentWindow?: string; hardReservations?: number; softReservations?: number
  history?: Array<{ label: string; used: number; reserved: number }>; futureWindows?: Array<{ label: string; pressure: number; reserved: string }>
}
export interface Reservation {
  id: string; workflowId: string; workflowName: string; resource: string; amount: string; type: ReservationType
  confidence: number; expiresIn: string; protectionValue: number; status: ReservationStatus
  createdAt?: string; workAtRisk?: string; predictedDemand?: string; pFailWithout?: number; pFailWith?: number
  deltaPFail?: number; normalizedCost?: number
}
export interface PredictionNode { label: string; detail: string; confidence: number; state: 'complete' | 'reserved' | 'predicted' }
export interface Prediction { workflowId: string; workflowName: string; nodes: PredictionNode[]; pathConfidence: number; remainingTokens: string }
export interface Metric { label: string; value: string; change: string; direction: 'up' | 'down' | 'neutral'; tone: 'blue' | 'rose' | 'amber' | 'green' | 'violet'; helper: string }
export interface ActivityEvent { id: string; type: EventType; title: string; detail: string; timestamp: string; category?: string; workflowId?: string; resource?: string; payload?: string }
export interface Policy { mode: PolicyMode; reservationCeiling: number; agingRate: number; confidenceThreshold: number; softThreshold?: number; predictionHorizon?: number; chainDepth?: string; riskWeight?: number }
export interface ExperimentPoint { label: string; baseline: number; sunkguard: number }
export interface Experiment { name: string; status: string; points: ExperimentPoint[]; ablation?: Array<{ label: string; wastedTokens: number; lateFailures: number; fairness: number; waitTime: number }>; metrics?: Array<{ label: string; value: string; baseline: string; direction: 'benefit' | 'cost' }> }

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: string;
  lastLoginAt?: number;
}

export interface AuthResponse {
  success: boolean;
  token?: string;
  expires_at?: number;
  user?: AuthUser;
  message?: string;
  error?: string;
}