import { useState, type KeyboardEvent } from "react";

interface ComposerProps {
  onSend: (message: string) => void;
  disabled: boolean;
}

export function Composer({ onSend, disabled }: ComposerProps) {
  const [text, setText] = useState("");

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    setText("");
    onSend(trimmed);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="composer">
      <textarea
        data-testid="chat-input"
        className="chat-input"
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask anything... (Enter to send, Shift+Enter for new line)"
        disabled={disabled}
      />
      <button
        type="button"
        data-testid="send-button"
        className="send-button"
        onClick={submit}
        disabled={disabled || !text.trim()}
      >
        {disabled ? "Sending…" : "Send"}
      </button>
    </div>
  );
}

