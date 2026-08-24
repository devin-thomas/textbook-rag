import { useEffect, useRef } from "react";
import { CloseIcon } from "../icons";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmDialog({ open, title, description, confirmLabel, busy, onConfirm, onClose }: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) cancelRef.current?.focus();
  }, [open]);

  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-description">
        <button className="icon-button dialog-close" onClick={onClose} aria-label="Close dialog"><CloseIcon /></button>
        <p className="eyebrow">Local history</p>
        <h2 id="confirm-title">{title}</h2>
        <p id="confirm-description">{description}</p>
        <div className="dialog-actions">
          <button ref={cancelRef} className="button secondary" onClick={onClose} disabled={busy}>Keep history</button>
          <button className="button danger" onClick={onConfirm} disabled={busy}>{busy ? "Deleting…" : confirmLabel}</button>
        </div>
      </section>
    </div>
  );
}
