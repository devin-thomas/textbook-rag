import { useEffect, useRef } from "react";
import { COURSES } from "../catalog";
import { CloseIcon } from "../icons";
import type { Source } from "../types";

interface ScopePopoverProps {
  open: boolean;
  sources: Source[];
  courseIds: string[];
  sourceIds: string[];
  onCourseIds: (ids: string[]) => void;
  onSourceIds: (ids: string[]) => void;
  onClose: () => void;
}

function toggle(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

export function ScopePopover({ open, sources, courseIds, sourceIds, onCourseIds, onSourceIds, onClose }: ScopePopoverProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div ref={panelRef} className="scope-popover" role="dialog" aria-label="Choose textbook scope">
      <div className="scope-header">
        <div><p className="eyebrow">Search scope</p><h3>Choose your books</h3></div>
        <button className="icon-button" onClick={onClose} aria-label="Close filters"><CloseIcon /></button>
      </div>
      <fieldset>
        <legend>Courses</legend>
        {COURSES.map((course) => (
          <label className="check-row" key={course.id}>
            <input type="checkbox" checked={courseIds.includes(course.id)} onChange={() => onCourseIds(toggle(courseIds, course.id))} />
            <span><strong>{course.id.replace("-", " ")}</strong><small>{course.name}</small></span>
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Textbooks</legend>
        {sources.map((source) => (
          <label className="check-row" key={source.id}>
            <input type="checkbox" checked={sourceIds.includes(source.id)} onChange={() => onSourceIds(toggle(sourceIds, source.id))} />
            <span>{source.title}</span>
          </label>
        ))}
      </fieldset>
      <div className="scope-footer">
        <button className="text-button" onClick={() => { onCourseIds([]); onSourceIds([]); }}>Reset to all books</button>
        <button className="button primary" onClick={onClose}>Use this scope</button>
      </div>
    </div>
  );
}
