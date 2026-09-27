import { useState } from "react";

export type AgentMode = "Premortem" | "Postmortem" | "Standing";
export type PermissionMode = "Read only" | "Propose patches" | "Apply patches";

interface ComposerProps {
  onSend: (text: string, mode: AgentMode) => void;
  disabled?: boolean;
}

export default function Composer({ onSend, disabled }: ComposerProps) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<AgentMode>("Premortem");
  const [permission, setPermission] = useState<PermissionMode>("Propose patches");

  function send() {
    if (!text.trim() || disabled) return;
    onSend(text, mode);
    setText("");
  }

  return (
    <div className="border-t border-border p-2.5 flex flex-col gap-2">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        placeholder="Follow up or start a new check"
        rows={2}
        className="bg-panel border border-border rounded px-2.5 py-2 text-[13px] text-gray-200 resize-none focus:outline-none focus:border-accent"
      />
      <div className="flex items-center gap-2">
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value as AgentMode)}
          className="bg-panel border border-border rounded px-2 py-1 text-[12px] text-gray-300"
        >
          <option>Premortem</option>
          <option>Postmortem</option>
          <option>Standing</option>
        </select>
        <select
          value={permission}
          onChange={(e) => setPermission(e.target.value as PermissionMode)}
          className="bg-panel border border-border rounded px-2 py-1 text-[12px] text-gray-300"
        >
          <option>Read only</option>
          <option>Propose patches</option>
          <option>Apply patches</option>
        </select>
        <button
          onClick={send}
          disabled={disabled || !text.trim()}
          className="ml-auto w-8 h-8 rounded-full bg-accent text-white flex items-center justify-center hover:bg-accent/90 disabled:opacity-40"
          title="Send"
        >
          {"↑"}
        </button>
      </div>
    </div>
  );
}
