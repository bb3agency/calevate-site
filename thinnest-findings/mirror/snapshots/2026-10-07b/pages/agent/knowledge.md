> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Knowledge

> What the agent answers from, and what it will refuse to guess at.

The agent answers from material you give it. When a search finds nothing, it
says it does not know rather than inventing an answer — that behaviour is the
point, and it is what makes the answers worth trusting.

## Ways to add material

<AccordionGroup>
  <Accordion title="A single page" icon="link">
    Paste a URL. Good for a returns policy or a pricing page you want indexed on
    its own.
  </Accordion>

  <Accordion title="A whole site crawl" icon="sitemap">
    Paste your homepage and choose a depth of 1 to 3 levels. You see the list of
    pages found and **pick which ones to index before anything is ingested** —
    a crawl is a proposal, not a commitment.
  </Accordion>

  <Accordion title="A sitemap" icon="map">
    Reaches pages a crawl cannot: unlinked pages, pages only reachable from
    search, anything not in your navigation. If a crawl missed something
    important, this is usually why.
  </Accordion>

  <Accordion title="Pasted text" icon="clipboard">
    For the policies that live in someone's head rather than on a page. Often
    the highest-value thing you will add.
  </Accordion>

  <Accordion title="Files" icon="file">
    `.txt`, `.md`, `.csv` and PDFs with a text layer.

    CSVs are chunked **row by row**, so a price never gets separated from its
    product.
  </Accordion>
</AccordionGroup>

## What is not supported

<Warning>
  **Scanned documents do not work.** There is no OCR. A PDF that is really a
  photograph of a page will ingest and contribute nothing, which is worse than
  failing loudly — so check that you can select the text in your PDF before
  uploading it.

  Also unsupported: images, video, and Word or Excel files. Export to PDF, CSV
  or text first.
</Warning>

## Getting good answers

**Fewer, better pages.** Four hundred pages of navigation chrome make retrieval
worse, not better. Index the pages that answer questions.

**Write the answer down somewhere.** If three customers a week ask something
your site never states, no amount of crawling will find it. Paste it in as text.

**Check the gaps report.** [Analytics](/workspace/analytics) lists the questions
the agent searched for and found nothing on. Each row is something worth adding
— it is the most directly useful page in the product.

## Knowledge and language

You do not need a knowledge base per language. Keep your material in one
language; the agent translates as it answers, in whichever of the 37 supported
languages the customer is using.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.