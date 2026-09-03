# Deferred Ideas

- Import LMS slides, assignments, notes, and other course material after textbook-only retrieval is proven.
- Public internet access or sharing the corpus with users outside the tailnet.
- Automated synchronization from the college LMS.
- Optional detailed tutor mode beyond the concise-answer default.

## Implemented: History filters and saved views

The history rail now provides a keyboard-accessible filter control so the student can filter saved questions by course, provider, answer mode, or date range without losing the current newest-first history order. Filter state stays in the client, while the API returns the conversation metadata needed to make the view accurate.

Delivered:

1. Return the existing conversation metadata needed for filtering, keeping the current conversation and message APIs backward compatible.
2. Keep the first pass client-side so filtering remains private, fast, and usable offline after history has loaded.
3. Add keyboard-accessible filter controls with a clear-all-filters action and a count of matching questions.
4. Add acceptance coverage for empty results, filter reset, mobile history drawer behavior, and preserving the selected question.

Acceptance criteria: filters never delete or reorder stored history, the active question remains visible when it matches, and the no-results state explains how to clear or change the filters.
