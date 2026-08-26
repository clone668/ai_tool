import type { ReactNode } from 'react'
import { AlertTriangle, LoaderCircle, X } from 'lucide-react'

interface OperationDialogProps {
  title: string
  target: string
  description: string
  confirmLabel: string
  busy: boolean
  tone?: 'default' | 'danger'
  children?: ReactNode
  onConfirm: () => void
  onClose: () => void
}

export function OperationDialog({
  title,
  target,
  description,
  confirmLabel,
  busy,
  tone = 'default',
  children,
  onConfirm,
  onClose,
}: OperationDialogProps) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={() => !busy && onClose()}>
      <section
        className="confirm-dialog operation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="operation-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className={`dialog-icon ${tone === 'danger' ? 'stop' : 'restart'}`}>
          <AlertTriangle size={22} />
        </div>
        <div className="dialog-copy">
          <h2 id="operation-title">{title}</h2>
          <p>{target}</p>
          <span>{description}</span>
        </div>
        <button
          className="icon-button dialog-close"
          onClick={onClose}
          disabled={busy}
          title="关闭"
          aria-label="关闭"
        >
          <X size={17} />
        </button>
        {children && <div className="operation-preview">{children}</div>}
        <div className="dialog-actions">
          <button className="secondary-button" onClick={onClose} disabled={busy} autoFocus>
            取消
          </button>
          <button
            className={`primary-button ${tone === 'danger' ? 'confirm-stop' : ''}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy && <LoaderCircle className="spin" size={16} />}
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>
  )
}
