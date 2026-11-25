import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: "" };

  static getDerivedStateFromError(err: Error): State {
    return { hasError: true, message: err.message || "Unexpected UI error." };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI ErrorBoundary caught:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="fatal-error" role="alert">
          <h2>Something went wrong</h2>
          <p>{this.state.message}</p>
          <button onClick={() => window.location.reload()}>Reload Session</button>
        </div>
      );
    }
    return this.props.children;
  }
}

