import type { ChatItem } from "../types";
import { MetaBar } from "./MetaBar";

interface MessageBubbleProps {
  item: ChatItem;
}

export function MessageBubble({ item }: MessageBubbleProps) {
  if (item.kind === "user") {
    return (
      <div className="message-row user-row">
        <div className="bubble user-bubble">
          <div className="bubble-role">You</div>
          <div className="bubble-text">{item.content}</div>
        </div>
      </div>
    );
  }

  if (item.kind === "error") {
    return (
      <div className="message-row error-row" role="alert" data-testid="error-message">
        <div className="bubble error-bubble">
          <div className="bubble-role">Error</div>
          <div className="bubble-text">{item.content}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="message-row assistant-row">
      <div className="bubble assistant-bubble" data-testid="assistant-message">
        <div className="bubble-role">Assistant</div>
        <div className="bubble-text">{item.content}</div>
        <MetaBar metadata={item.metadata} />
      </div>
    </div>
  );
}

