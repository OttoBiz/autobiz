"use client"

import ReactMarkdown from "react-markdown"

/** Heuristic: common markdown cues without treating every * as MD. */
export function looksLikeMarkdown(s: string): boolean {
  if (!s?.trim() || s.length < 2) return false
  return /(^|\n)\s{0,3}[#>\-*`\d]|(\*\*|__)|`[^`\n]+`|\[[^\]\n]+\]\([^)]+\)/.test(s)
}

const mdBase =
  "text-sm break-words [&_p]:mb-1 [&_p:last-child]:mb-0 [&_ul]:my-1 [&_ol]:my-1 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:my-0.5 [&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-sm [&_h3]:font-medium [&_blockquote]:border-l-2 [&_blockquote]:pl-2 [&_blockquote]:opacity-90 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:p-2 [&_pre]:text-xs"

const mdLight =
  "[&_a]:text-blue-100 [&_a]:underline [&_code]:rounded [&_code]:bg-white/20 [&_code]:px-1 [&_pre]:bg-black/20"

const mdDark =
  "[&_a]:text-blue-600 [&_a]:underline [&_code]:rounded [&_code]:bg-gray-200 [&_code]:px-1 [&_pre]:bg-gray-200"

export function ChatMessageBody({
  content,
  invert,
}: {
  content: string
  invert?: boolean
}) {
  if (!looksLikeMarkdown(content)) {
    return <span className="whitespace-pre-wrap break-words">{content}</span>
  }
  return (
    <div className={`${mdBase} ${invert ? mdLight : mdDark}`}>
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  )
}
