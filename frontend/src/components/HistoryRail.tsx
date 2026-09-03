import { useMemo, useState } from "react";
import { CloseIcon, SearchIcon, TrashIcon } from "../icons";
import type { ConversationSummary } from "../types";

interface HistoryRailProps {
  conversations: ConversationSummary[];
  selectedId?: string;
  mobileOpen: boolean;
  onSelect: (id: string) => void;
  onDelete: (conversation: ConversationSummary) => void;
  onClear: () => void;
  onCloseMobile: () => void;
}

function dayLabel(value: string): string {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return "Today";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: date.getFullYear() !== today.getFullYear() ? "numeric" : undefined }).format(date);
}

export function HistoryRail({ conversations, selectedId, mobileOpen, onSelect, onDelete, onClear, onCloseMobile }: HistoryRailProps) {
  const [search, setSearch] = useState("");
  const grouped = useMemo(() => {
    const result = new Map<string, ConversationSummary[]>();
    conversations.filter((item) => item.title.toLowerCase().includes(search.toLowerCase())).forEach((item) => {
      const label = dayLabel(item.updatedAt);
      result.set(label, [...(result.get(label) ?? []), item]);
    });
    return result;
  }, [conversations, search]);

  return (
    <>
      {mobileOpen && <button className="drawer-backdrop" aria-label="Close history" onClick={onCloseMobile} />}
      <aside className={`history-rail ${mobileOpen ? "mobile-open" : ""}`} aria-label="Question history">
        <div className="rail-title-row"><h2>History</h2><button className="icon-button mobile-only" onClick={onCloseMobile} aria-label="Close history"><CloseIcon /></button></div>
        <label className="search-field"><SearchIcon /><span className="sr-only">Find a question</span><input aria-label="Find a question" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a question" /></label>
        <div className="history-list">
          {grouped.size === 0 ? (
            <div className="empty-history"><span aria-hidden="true">◇</span><h3>{search ? "No matching questions" : "Your study trail starts here"}</h3><p>{search ? "Try another phrase." : "Questions you ask will be saved locally on Titan."}</p></div>
          ) : [...grouped].map(([label, items]) => (
            <section className="history-group" key={label} aria-label={label}>
              <h3>{label}</h3>
              {items.map((item) => (
                <div className={`history-row ${selectedId === item.id ? "selected" : ""}`} key={item.id}>
                  <button type="button" className="history-select" onClick={() => { onSelect(item.id); onCloseMobile(); }} aria-current={selectedId === item.id ? "page" : undefined}>
                    <span>{item.title}</span><time>{new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(item.updatedAt))}</time>
                  </button>
                  <button type="button" className="history-delete icon-button" onClick={() => onDelete(item)} aria-label={`Delete ${item.title}`}><TrashIcon /></button>
                </div>
              ))}
            </section>
          ))}
        </div>
        <button type="button" className="clear-history text-button" onClick={onClear} disabled={conversations.length === 0}><TrashIcon /> Clear history…</button>
      </aside>
    </>
  );
}
