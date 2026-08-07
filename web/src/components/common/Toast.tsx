import React from 'react';

export interface ToastMessage {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error';
  title: string;
  message?: string;
}

export interface ToastProps {
  toasts: ToastMessage[];
  onDismiss: (id: string) => void;
}

export const ToastContainer: React.FC<ToastProps> = ({ toasts, onDismiss }) => {
  if (!toasts.length) return null;

  return (
    <div className="toast-container">
      {toasts.map((toast) => {
        const badgeColor =
          toast.type === 'success'
            ? 'var(--accent-emerald)'
            : toast.type === 'error'
            ? 'var(--accent-rose)'
            : toast.type === 'warning'
            ? 'var(--accent-amber)'
            : 'var(--accent-primary)';

        return (
          <div key={toast.id} className="toast">
            <div
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: badgeColor,
              }}
            />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{toast.title}</div>
              {toast.message && (
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                  {toast.message}
                </div>
              )}
            </div>
            <button
              onClick={() => onDismiss(toast.id)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                fontSize: '1rem',
              }}
            >
              &times;
            </button>
          </div>
        );
      })}
    </div>
  );
};
