"use client";

import React, { useMemo } from "react";
import katex from "katex";

// Renders inline or block math using KaTeX
function RenderMath({ formula, displayMode }) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(formula, {
        displayMode,
        throwOnError: false,
      });
    } catch (err) {
      console.error("KaTeX error:", err);
      return formula;
    }
  }, [formula, displayMode]);

  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

// Parses inline elements like bold (**text**) and code (`code`)
function parseInlineMarkdown(text) {
  let elements = [text];

  // 1. Process inline code: `code`
  elements = elements.flatMap((el, idx) => {
    if (typeof el !== "string") return el;
    const parts = el.split(/`([^`]+)`/g);
    return parts.map((part, i) => {
      if (i % 2 === 1) {
        return (
          <code
            key={`code-${idx}-${i}`}
            className="bg-zinc-800 text-indigo-300 font-mono text-xs px-1.5 py-0.5 rounded border border-zinc-700/50"
          >
            {part}
          </code>
        );
      }
      return part;
    });
  });

  // 2. Process bold text: **text**
  elements = elements.flatMap((el, idx) => {
    if (typeof el !== "string") return el;
    const parts = el.split(/\*\*([^*]+)\*\*/g);
    return parts.map((part, i) => {
      if (i % 2 === 1) {
        return (
          <strong key={`bold-${idx}-${i}`} className="font-bold text-white">
            {part}
          </strong>
        );
      }
      return part;
    });
  });

  return elements;
}

// Renders paragraph blocks, headings, lists, and spacing
function RenderTextBlock({ text }) {
  const lines = text.split("\n");
  const blocks = [];
  let currentList = [];
  let listKeyCounter = 0;

  const flushList = () => {
    if (currentList.length > 0) {
      blocks.push(
        <ul
          key={`ul-${listKeyCounter++}`}
          className="list-disc pl-6 mb-4 space-y-1 text-zinc-300"
        >
          {currentList}
        </ul>
      );
      currentList = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Check for Headings: #, ##, ###, etc.
    const headerMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headerMatch) {
      flushList();
      const level = headerMatch[1].length;
      const content = parseInlineMarkdown(headerMatch[2]);

      const headingClasses = {
        1: "text-2xl font-bold text-white mt-6 mb-3",
        2: "text-xl font-bold text-white mt-5 mb-2.5",
        3: "text-lg font-bold text-white mt-4 mb-2",
        4: "text-base font-bold text-white mt-3.5 mb-1.5",
        5: "text-sm font-bold text-white mt-3 mb-1",
        6: "text-xs font-bold text-white mt-3 mb-1",
      };

      const HeadingTag = `h${level}`;
      blocks.push(
        <HeadingTag
          key={`h-${i}`}
          className={headingClasses[level] || headingClasses[3]}
        >
          {content}
        </HeadingTag>
      );
      continue;
    }

    // Check for Bullet Lists: starts with "- " or "* "
    const listMatch = line.match(/^[-*]\s+(.*)$/);
    if (listMatch) {
      const content = parseInlineMarkdown(listMatch[1]);
      currentList.push(
        <li key={`li-${i}`} className="leading-relaxed">
          {content}
        </li>
      );
      continue;
    }

    // Check for empty line (paragraph break)
    if (line.trim() === "") {
      flushList();
      continue;
    }

    // Default: normal paragraph text line
    flushList();
    const content = parseInlineMarkdown(line);
    blocks.push(
      <p key={`p-${i}`} className="mb-3.5 leading-relaxed text-zinc-200">
        {content}
      </p>
    );
  }

  flushList();
  return <>{blocks}</>;
}

// Main component that splits content into math and text tokens
export default function MathMarkdownRenderer({ content }) {
  const tokens = useMemo(() => {
    if (!content) return [];
    
    const result = [];
    let index = 0;

    while (index < content.length) {
      // 1. Block Math: \[ ... \]
      if (content.startsWith("\\[", index)) {
        const start = index;
        const end = content.indexOf("\\]", start + 2);
        if (end !== -1) {
          result.push({
            type: "block-math",
            content: content.slice(start + 2, end),
          });
          index = end + 2;
          continue;
        }
        // Unclosed block math (streaming): fallback to text
        result.push({
          type: "text",
          content: content.slice(start),
        });
        break;
      }

      // 2. Block Math: $$ ... $$
      if (content.startsWith("$$", index)) {
        const start = index;
        const end = content.indexOf("$$", start + 2);
        if (end !== -1) {
          result.push({
            type: "block-math",
            content: content.slice(start + 2, end),
          });
          index = end + 2;
          continue;
        }
        // Unclosed block math (streaming): fallback to text
        result.push({
          type: "text",
          content: content.slice(start),
        });
        break;
      }

      // 3. Inline Math: \( ... \)
      if (content.startsWith("\\(", index)) {
        const start = index;
        const end = content.indexOf("\\)", start + 2);
        if (end !== -1) {
          result.push({
            type: "inline-math",
            content: content.slice(start + 2, end),
          });
          index = end + 2;
          continue;
        }
        // Unclosed inline math (streaming): fallback to text
        result.push({
          type: "text",
          content: content.slice(start),
        });
        break;
      }

      // 4. Inline Math: $ ... $ (ensuring not followed by whitespace)
      if (content.startsWith("$", index)) {
        const start = index;
        const nextChar = content.charAt(start + 1);
        if (nextChar && nextChar !== " " && nextChar !== "\n") {
          const end = content.indexOf("$", start + 1);
          if (end !== -1) {
            result.push({
              type: "inline-math",
              content: content.slice(start + 1, end),
            });
            index = end + 1;
            continue;
          }
        }
      }

      // 5. Normal text: find the next delimiter
      let nextSpecial = -1;
      const searchTargets = ["\\[", "$$", "\\(", "$"];
      for (const target of searchTargets) {
        const pos = content.indexOf(target, index + 1);
        if (pos !== -1 && (nextSpecial === -1 || pos < nextSpecial)) {
          nextSpecial = pos;
        }
      }

      if (nextSpecial !== -1) {
        result.push({
          type: "text",
          content: content.slice(index, nextSpecial),
        });
        index = nextSpecial;
      } else {
        result.push({
          type: "text",
          content: content.slice(index),
        });
        break;
      }
    }

    return result;
  }, [content]);

  return (
    <div className="math-markdown-content text-zinc-150">
      {tokens.map((token, i) => {
        if (token.type === "block-math") {
          return (
            <div
              key={`bm-${i}`}
              className="my-4 py-1 overflow-x-auto max-w-full text-center scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent"
            >
              <RenderMath formula={token.content} displayMode={true} />
            </div>
          );
        }
        if (token.type === "inline-math") {
          return (
            <RenderMath
              key={`im-${i}`}
              formula={token.content}
              displayMode={false}
            />
          );
        }
        return <RenderTextBlock key={`txt-${i}`} text={token.content} />;
      })}
    </div>
  );
}
