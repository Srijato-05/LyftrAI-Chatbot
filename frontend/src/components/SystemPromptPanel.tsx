import { useState } from "react";

interface SystemPromptPanelProps {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}

export function SystemPromptPanel({ value, onChange, disabled }: SystemPromptPanelProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="system-panel">
      <button
        type="button"
        className="system-toggle"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span>{open ? "▾" : "▸"} Session System Prompt (optional)</span>
        {value.trim() && <span className="system-active-dot">Active</span>}
      </button>

      {open && (
        <div className="system-body">
          <textarea
            data-testid="system-prompt-input"
            className="system-textarea"
            rows={2}
            value={value}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Optional instructions for the assistant in this session (e.g., Answer concisely in 2 sentences)."
          />
        </div>
      )}
    </div>
  );
}

