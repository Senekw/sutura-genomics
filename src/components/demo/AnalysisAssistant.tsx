"use client";

import { useRef, useState } from "react";
import { Sparkles, Send, ChevronDown, RotateCcw } from "lucide-react";

import type { DemoDataset } from "@/lib/demoDatasets";
import { analyzeRun, type Run } from "@/lib/demoRuns";
import {
  askChat,
  fullAnalysis,
  suggestedQuestions,
  type ChatReply,
  type ChatTurn,
} from "@/lib/analysisChat";

type Msg = { role: "user" | "assistant"; text: string; source?: ChatReply["source"] };

export default function AnalysisAssistant({ ds, run }: { ds: DemoDataset; run: Run }) {
  const [expanded, setExpanded] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const suggestions = suggestedQuestions(ds, run);

  const send = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    setInput("");

    // The turns that existed before this question are the conversation the
    // model needs in order to resolve follow-ups like "why?". Notices (rate
    // limits, outages) aren't part of the discussion, so they're left out.
    const history: ChatTurn[] = messages
      .filter((m) => m.source !== "notice")
      .map((m) => ({ role: m.role, text: m.text }));

    setMessages((m) => [...m, { role: "user", text: question }]);
    setBusy(true);
    const reply = await askChat(question, ds, run, history);
    setMessages((m) => [...m, { role: "assistant", text: reply.answer, source: reply.source }]);
    setBusy(false);
    requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: 1e6, behavior: "smooth" }));
  };

  return (
    <div className="mt-4 overflow-hidden rounded-2xl border border-[#e3dbff] bg-gradient-to-b from-[#faf8ff] to-white">
      <div className="flex items-center gap-2 border-b border-[#efeaff] px-6 py-4">
        <span className="grid h-6 w-6 place-items-center rounded-md bg-[#6633ee]/10">
          <Sparkles className="h-3.5 w-3.5 text-[#6633ee]" strokeWidth={2} />
        </span>
        <h2 className="text-[15px] font-normal text-foreground">Analysis assistant</h2>
        {messages.length > 0 && (
          <button
            type="button"
            onClick={() => setMessages([])}
            className="ml-auto inline-flex items-center gap-1 text-[12px] font-light text-muted-foreground transition-colors hover:text-foreground"
          >
            <RotateCcw className="h-3 w-3" strokeWidth={2} />
            Clear
          </button>
        )}
      </div>

      <div className="px-6 py-5">
        {/* Grounded one-line read */}
        <p className="text-[14px] font-light leading-relaxed text-foreground">{analyzeRun(run)}</p>

        {/* Illustrative datasets are labelled here as well as in the model's
            context, so the caveat is visible without having to ask for it. */}
        {!ds.real && (
          <p className="mt-2 text-[12px] font-light leading-relaxed text-muted-foreground">
            {ds.name} is illustrative demo data — these figures show how a result reads, not a
            measured outcome.
          </p>
        )}

        {/* See full analysis */}
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-normal text-[#6633ee] transition-colors hover:text-[#5a2ce0]"
        >
          {expanded ? "Hide full analysis" : "See full analysis"}
          <ChevronDown className={"h-3.5 w-3.5 transition-transform " + (expanded ? "rotate-180" : "")} strokeWidth={2} />
        </button>
        {expanded && (
          <div className="mt-3 whitespace-pre-line rounded-xl border border-border bg-white p-4 text-[13px] font-light leading-relaxed text-muted-foreground">
            {fullAnalysis(ds, run)}
          </div>
        )}

        {/* Chat */}
        {messages.length > 0 && (
          <div
            ref={scrollRef}
            className="mt-4 max-h-72 space-y-3 overflow-y-auto pr-1"
            role="log"
            aria-live="polite"
            aria-label="Analysis assistant conversation"
          >
            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
                <div
                  className={
                    "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed " +
                    (m.role === "user"
                      ? "bg-[#6633ee] font-normal text-white"
                      : "border border-border bg-white font-light text-foreground")
                  }
                >
                  <p className="whitespace-pre-line">{m.text}</p>
                  {/* Notices (rate limits, outages) aren't answers, so they
                      carry no provenance line. */}
                  {m.role === "assistant" && m.source !== "notice" && (
                    <p className="mt-1.5 flex items-center gap-1 text-[10.5px] font-light text-muted-foreground">
                      <Sparkles className="h-2.5 w-2.5 text-[#6633ee]/70" strokeWidth={1.8} />
                      {m.source === "gemini" ? "Gemini · grounded in run metrics" : "Rule-based summary"}
                    </p>
                  )}
                </div>
              </div>
            ))}
            {busy && (
              <div className="flex justify-start">
                <div className="inline-flex items-center gap-2 rounded-2xl border border-border bg-white px-3.5 py-2.5 text-[12px] font-light text-muted-foreground">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[#e7e1ff] border-t-[#6633ee]" />
                  Thinking…
                </div>
              </div>
            )}
          </div>
        )}

        {messages.length === 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {suggestions.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => send(q)}
                className="rounded-full border border-border bg-white px-3 py-1.5 text-[12.5px] font-light text-muted-foreground transition-colors hover:border-[#6633ee]/40 hover:text-foreground"
              >
                {q}
              </button>
            ))}
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="mt-4 flex items-center gap-2"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about this alignment…"
            className="h-11 flex-1 rounded-full border border-input bg-white px-4 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground/50 focus:border-[#6633ee] focus:ring-2 focus:ring-[#6633ee]/15"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[#6633ee] text-white transition-all hover:-translate-y-0.5 hover:bg-[#5a2ce0] disabled:pointer-events-none disabled:opacity-40"
            aria-label="Send"
          >
            <Send className="h-4 w-4" strokeWidth={2} />
          </button>
        </form>
      </div>
    </div>
  );
}
