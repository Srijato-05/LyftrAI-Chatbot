import type { ChatMetadata } from "../types";

interface MetaBarProps {
  metadata: ChatMetadata;
}

export function MetaBar({ metadata }: MetaBarProps) {
  const isCache = metadata.resolution_source === "LLM_CACHE";

  return (
    <div className="meta-bar">
      <span
        data-testid="meta-source"
        className={`meta-badge ${isCache ? "badge-cache" : "badge-live"}`}
      >
        {metadata.resolution_source}
      </span>

      <span className="meta-chip">
        <span className="meta-label">model:</span>
        <span data-testid="meta-model">{metadata.model}</span>
      </span>

      <span className="meta-chip">
        <span className="meta-label">latency:</span>
        <span data-testid="meta-latency">{metadata.latency_ms} ms</span>
      </span>

      <span className="meta-chip">
        <span className="meta-label">in:</span>
        <span data-testid="meta-input-tokens">{metadata.input_tokens}</span>
      </span>

      <span className="meta-chip">
        <span className="meta-label">out:</span>
        <span data-testid="meta-output-tokens">{metadata.output_tokens}</span>
      </span>

      {metadata.key_id && (
        <span className="meta-chip meta-extra">
          <span className="meta-label">key:</span>
          <span>{metadata.key_id}</span>
        </span>
      )}

      {metadata.fallback_attempts > 0 && (
        <span className="meta-chip meta-warn">
          <span className="meta-label">fallbacks:</span>
          <span>{metadata.fallback_attempts}</span>
        </span>
      )}
    </div>
  );
}

