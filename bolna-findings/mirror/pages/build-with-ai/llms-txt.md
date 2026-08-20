> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# llms.txt & llms-full.txt

> Machine-readable versions of these docs for feeding into an LLM's context window.

These docs publish two plain-text files built for LLMs and AI agents to consume directly, without scraping HTML.

<CardGroup cols={2}>
  <Card title="llms.txt" icon="list" href="https://www.bolna.ai/docs/llms.txt">
    A structured index of every page in these docs — titles and descriptions — for fast lookup by an LLM before it decides what to fetch in full.
  </Card>

  <Card title="llms-full.txt" icon="file-lines" href="https://www.bolna.ai/docs/llms-full.txt">
    The complete Bolna documentation concatenated into a single Markdown file, for pasting into a chat context or feeding to a RAG pipeline.
  </Card>
</CardGroup>

## When to use which

* Use **llms.txt** when an agent needs to decide which pages are relevant before reading them.
* Use **llms-full.txt** when you want the entire documentation set in one context window — for example, priming an LLM before asking it to write Bolna API integration code.

## Per-page AI actions

Every individual page in these docs also has its own AI actions menu:

* **Copy page** — copy the page content as Markdown
* **View as Markdown** — open the raw Markdown source for that page
* **Open in ChatGPT** — ask ChatGPT questions about that page
* **Open in Claude** — ask Claude questions about that page

For API-level integration facts an LLM needs (base URL, auth, response shapes, status lifecycles), see [AGENTS.md](/docs/build-with-ai/agents-md).
