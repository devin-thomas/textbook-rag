export type ProviderChoice = "auto" | "nvidia" | "ollama";

export interface Course {
  id: string;
  name: string;
}

export interface Source {
  id: string;
  title: string;
  course_ids: string[];
  indexed?: boolean;
  status?: string;
}

export interface AppHealth {
  status: string;
  ollama: {
    configured: boolean;
    status?: string;
  };
}

export interface Evidence {
  id: string;
  sourceId: string;
  sourceTitle: string;
  page: number;
  pageLabel?: string;
  excerpt: string;
  rank: number;
  semanticScore?: number;
  lexicalScore?: number;
  fusedScore?: number;
}

export interface Citation {
  id: string;
  evidenceId: string;
  sourceId: string;
  sourceTitle: string;
  page: number;
  pageLabel?: string;
  pdfUrl?: string;
}

export type AnswerStatus = "idle" | "loading" | "answered" | "insufficient_evidence" | "provider_abstention" | "error";

export interface Answer {
  status: Exclude<AnswerStatus, "idle" | "loading">;
  question: string;
  text: string;
  citations: Citation[];
  evidence: Evidence[];
  requestedProvider: ProviderChoice;
  actualProvider?: "nvidia" | "ollama";
  fallback: boolean;
  fallbackReason?: string;
  retrievalFallback: boolean;
  selectAllThatApply: boolean;
  conversationId?: string;
  messageId?: string;
  error?: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updatedAt: string;
  courseIds?: string[];
  providerChoice?: ProviderChoice;
  actualProvider?: "nvidia" | "ollama";
  selectAllThatApply?: boolean;
}

export interface QueryRequest {
  question: string;
  provider: ProviderChoice;
  course_ids?: string[];
  source_ids?: string[];
  conversation_id?: string;
  select_all_that_apply?: boolean;
}
