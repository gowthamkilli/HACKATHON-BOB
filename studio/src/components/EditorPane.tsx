import Editor from "@monaco-editor/react";

interface EditorPaneProps {
  path: string | null;
  content: string;
  onChange: (value: string) => void;
}

function languageFor(path: string | null): string {
  if (!path) return "plaintext";
  if (path.endsWith(".py")) return "python";
  if (path.endsWith(".md")) return "markdown";
  if (path.endsWith(".json")) return "json";
  if (path.endsWith(".ts") || path.endsWith(".tsx")) return "typescript";
  return "plaintext";
}

export default function EditorPane({ path, content, onChange }: EditorPaneProps) {
  if (!path) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-600 text-sm">
        Open a file from the Explorer to start editing.
      </div>
    );
  }
  return (
    <div className="flex-1 min-h-0">
      <Editor
        height="100%"
        theme="vs-dark"
        language={languageFor(path)}
        value={content}
        onChange={(v) => onChange(v ?? "")}
        options={{
          fontFamily: "IBM Plex Mono, monospace",
          fontSize: 13,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          automaticLayout: true,
        }}
      />
    </div>
  );
}
