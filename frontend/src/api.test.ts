import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, getConversation, getSources } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("API normalization", () => {
  it("rebuilds history citations from citation_order evidence", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      id: "conv-1",
      title: "Virtual memory",
      messages: [
        { id: "u1", role: "user", text: "What is virtual memory?", provider_choice: "auto" },
        { id: "a1", role: "assistant", text: "It uses paging. [1]", provider_choice: "auto", actual_provider: "ollama", fallback_used: true, status: "ok", evidence: [
          { chunk_id: "chunk-1", source_id: "book-1", source_title: "Operating Systems", physical_page: 42, page_label: "31", excerpt: "Pages can be moved to disk.", rank: 1, semantic_score: .81, fts_score: 6.2, fusion_score: .03, citation_order: 1 },
        ] },
        { id: "u2", role: "user", text: "This turn never finished", provider_choice: "nvidia" },
      ],
    }), { status: 200 })));

    const result = await getConversation("conv-1");
    expect(result.citations).toHaveLength(1);
    expect(result.citations[0]).toMatchObject({ evidenceId: "chunk-1", page: 42 });
    expect(result.evidence[0]).toMatchObject({ lexicalScore: 6.2, fusedScore: .03 });
    expect(result.fallback).toBe(true);
    expect(result.question).toBe("What is virtual memory?");
  });

  it("returns an explicit error for a conversation with only a dangling user turn", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      id: "conv-2",
      title: "Interrupted question",
      messages: [{ id: "u2", role: "user", text: "Did this finish?", provider_choice: "ollama" }],
    }), { status: 200 })));
    const result = await getConversation("conv-2");
    expect(result.status).toBe("error");
    expect(result.question).toBe("Did this finish?");
    expect(result.error).toMatch(/did not finish/);
  });

  it("surfaces the backend's stable nested error message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "retrieval_unavailable", message: "Embedding tunnel is offline" } }), { status: 503 })));
    try {
      await getSources();
      throw new Error("Expected getSources to reject");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.code).toBe("retrieval_unavailable");
      expect(apiError.message).toBe("Embedding tunnel is offline");
    }
  });
});
