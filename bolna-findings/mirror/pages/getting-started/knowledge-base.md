> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Build Knowledge Base with PDFs & URLs

> Upload PDFs and add URLs to create knowledge bases for your Bolna Voice AI agents. Enable context-aware responses with RAG-powered retrieval.

## What is Knowledge Base?

Knowledge Base allows you to upload documents and add URLs that your AI agent can reference during conversations. Using RAG (Retrieval-Augmented Generation), your agent retrieves relevant information and provides accurate, context-aware responses.

<Frame caption="Knowledge Base Page on Bolna Platform">
  <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/knowledge-base/knowledge-base-overview.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=09fbc8cc4e813ba639bce22680818c00" alt="Knowledge Base page showing sidebar navigation, uploaded PDFs and URLs with RAG IDs, status, and Add Knowledge Base button" width="1024" height="451" data-path="images/getting-started/knowledge-base/knowledge-base-overview.png" />
</Frame>

***

## How to Access Knowledge Base

<Steps>
  <Step title="Go to Bolna Platform">
    Navigate to [platform.bolna.ai](https://platform.bolna.ai/)
  </Step>

  <Step title="Open Knowledge Base">
    Click **Knowledge Base** in the left sidebar.
  </Step>

  <Step title="Add New Content">
    Click the blue **Add Knowledge Base** button to get started.
  </Step>
</Steps>

***

## Adding a Knowledge Base

<Tabs>
  <Tab title="Upload PDF">
    Upload PDF documents for your agent to reference.

    <Frame caption="Upload PDF Modal">
      <img src="https://mintcdn.com/bolna-54a2d4fe/4u8diftRGdXM_lrP/images/getting-started/knowledge-base/upload-pdf.png?fit=max&auto=format&n=4u8diftRGdXM_lrP&q=85&s=d6ecdcee8312dcf6d61765d850995e50" alt="Add Knowledge Base modal with Upload PDF tab showing drag and drop area and Language Support dropdown" width="699" height="516" data-path="images/getting-started/knowledge-base/upload-pdf.png" />
    </Frame>

    <Steps>
      <Step title="Click Add Knowledge Base">
        Open the modal from the main Knowledge Base page.
      </Step>

      <Step title="Select Upload PDF Tab">
        The **Upload PDF** tab is selected by default.
      </Step>

      <Step title="Upload Your File">
        Drag and drop your PDF file, or click **"click to browse"** to select.
      </Step>

      <Step title="Select Language Support">
        Choose **English (Default)** or **Multilingual (Hindi, Tamil, etc.)** from the **Language Support** dropdown.
      </Step>

      <Step title="Process Document">
        Click **Upload PDF** to start processing.
      </Step>
    </Steps>

    <Note>
      Only `.pdf` files are supported for document upload.
    </Note>
  </Tab>

  <Tab title="Add URL">
    Add website URLs for your agent to reference.

    <Frame caption="Add URL Modal">
      <img src="https://mintcdn.com/bolna-54a2d4fe/4u8diftRGdXM_lrP/images/getting-started/knowledge-base/add-url.png?fit=max&auto=format&n=4u8diftRGdXM_lrP&q=85&s=e464379456753b09e2e05ff05496bd6d" alt="Add Knowledge Base modal with Add URL tab showing website URL input field and Language Support dropdown" width="699" height="516" data-path="images/getting-started/knowledge-base/add-url.png" />
    </Frame>

    <Steps>
      <Step title="Click Add Knowledge Base">
        Open the modal from the main Knowledge Base page.
      </Step>

      <Step title="Select Add URL Tab">
        Click the **Add URL** tab.
      </Step>

      <Step title="Enter Website URL">
        Paste the full URL (e.g., `https://example.com`).
      </Step>

      <Step title="Select Language Support">
        Choose **English (Default)** or **Multilingual (Hindi, Tamil, etc.)** from the **Language Support** dropdown.
      </Step>

      <Step title="Process Content">
        Click **Add URL** to start processing.
      </Step>
    </Steps>

    <Tip>
      Add your company website, FAQ pages, or product documentation URLs for comprehensive agent knowledge.
    </Tip>
  </Tab>
</Tabs>

***

## Multilingual Knowledge Bases

By default, knowledge bases are optimized for English content. If your documents are in **non-English languages** (Hindi, Spanish, French, etc.) or you need **cross-lingual retrieval** (e.g., query in English, retrieve from Hindi documents), enable **Multilingual** language support when creating a knowledge base.

| Mode                       | Best for                                                               |
| -------------------------- | ---------------------------------------------------------------------- |
| **Default** (no selection) | English-only documents and queries                                     |
| **Multilingual**           | Non-English documents, mixed-language queries, cross-lingual retrieval |

<Warning>
  Choose the language support mode **before** uploading. Existing knowledge bases cannot be switched between default and multilingual — you'll need to create a new one.
</Warning>

<Tip>
  If your agent handles calls in multiple languages using [multilingual voice support](/docs/customizations/multilingual-languages-support), pair it with a multilingual knowledge base for consistent cross-lingual performance.
</Tip>

***

## Managing Your Knowledge Bases

Your uploaded knowledge bases are displayed in a table with full management capabilities.

| Column      | Description                                            |
| ----------- | ------------------------------------------------------ |
| **RAG ID**  | Unique identifier for the knowledge base               |
| **Source**  | Original file name or URL                              |
| **Type**    | Content type (Pdf, Url)                                |
| **Created** | When the knowledge base was added                      |
| **Status**  | Processing status (`processed`, `processing`, `error`) |
| **Delete**  | Remove the knowledge base                              |

<Info>
  Wait for the status to show **"processed"** before connecting to your agent. If status shows **"error"**, try re-uploading the file.
</Info>

***

## Connecting to Your Agent

<Warning>
  **Don't forget this step!** Knowledge bases must be connected to your agent in the LLM Tab to take effect.
</Warning>

<Frame caption="Connect Knowledge Base in LLM Tab">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/llm-knowledge-base.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=c8489689cf946ce1dcaf9101ac88fe21" alt="LLM Tab showing Add knowledge base multi-select dropdown with URLs and PDFs" width="1024" height="583" data-path="images/getting-started/agent-setup/llm-knowledge-base.png" />
</Frame>

<Steps>
  <Step title="Open LLM Tab">
    Go to your agent's **[LLM Tab](/docs/agent-setup/llm-tab)**.
  </Step>

  <Step title="Find Knowledge Base Section">
    Locate **Add knowledge base (Multi-select)**.
  </Step>

  <Step title="Select Knowledge Bases">
    Check one or more knowledge bases from the dropdown.
  </Step>

  <Step title="Save Changes">
    Click **Save agent** to apply changes.
  </Step>
</Steps>

<Tip>
  You can connect multiple knowledge bases to a single agent for comprehensive responses across different topics.
</Tip>

***

## Use Cases

<CardGroup cols={2}>
  <Card title="Product Documentation" icon="box">
    Answer questions about your products and services
  </Card>

  <Card title="FAQ Responses" icon="circle-question">
    Provide accurate answers from your FAQ pages
  </Card>

  <Card title="Policy Information" icon="file-contract">
    Reference company policies during calls
  </Card>

  <Card title="Training Materials" icon="graduation-cap">
    Help agents access training and onboarding content
  </Card>
</CardGroup>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="LLM Tab" icon="brain" href="/docs/agent-setup/llm-tab">
    Connect knowledge base to your agent
  </Card>

  <Card title="Agent Tab" icon="file-lines" href="/docs/agent-setup/agent-tab">
    Configure prompts to use knowledge
  </Card>

  <Card title="Guardrails Guide" icon="shield" href="/docs/guardrails">
    Set safety rules and structured responses
  </Card>

  <Card title="Prompting Guide" icon="lightbulb" href="/docs/guides/prompting/prompting-guide">
    Prompting best practices
  </Card>
</CardGroup>
