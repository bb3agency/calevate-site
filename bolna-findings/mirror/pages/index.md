> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Home

> Bolna — the AI Voice API for India. Deploy multilingual conversational Voice AI agents to automate calls, qualify leads, boost sales, support customers, & more.

export const Card = ({icon, title, description, href}) => {
  const [isHovered, setIsHovered] = React.useState(false);
  return <a className="group block p-7 rounded-xl border no-underline text-center" href={href} style={{
    borderColor: isHovered ? '#d4e5f7' : '#e8f0f8',
    transform: isHovered ? 'scale(1.02)' : 'scale(1)',
    transition: 'all 0.4s ease'
  }} onMouseEnter={() => setIsHovered(true)} onMouseLeave={() => setIsHovered(false)}>
      <Icon icon={icon} iconType="solid" size={30} className="text-blue-600 dark:text-blue-400 mb-3 mx-auto" />
      <h3 className="text-base font-semibold text-gray-900 dark:text-zinc-100 mb-2">{title}</h3>
      <p className="text-sm text-gray-600 dark:text-zinc-400 leading-relaxed">{description}</p>
    </a>;
};

<div className="relative min-h-[calc(100vh-180px)] flex items-center justify-center">
  <div className="absolute inset-0 -z-10 overflow-hidden">
    <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[700px] h-[350px] bg-gradient-to-r from-blue-400/5 via-violet-400/5 to-emerald-400/5 dark:from-blue-500/10 dark:via-violet-500/10 dark:to-emerald-500/10 rounded-full blur-3xl" />
  </div>

  <div className="max-w-4xl mx-auto px-6 text-center">
    <h1 className="text-4xl lg:text-5xl font-bold text-gray-900 dark:text-white tracking-tight mb-6">
      Bolna Documentation
    </h1>

    <p className="max-w-2xl mx-auto text-lg text-gray-600 dark:text-zinc-400 mb-12">
      Create conversational voice agents to <strong>qualify leads</strong>, <strong>boost sales</strong>, <strong>automate support</strong>, <strong>streamline hiring</strong>, and more.
    </p>

    <div className="grid sm:grid-cols-2 gap-5 max-w-3xl mx-auto mb-12">
      <Card icon="sparkles" title="Introduction" description="Platform overview and live demo" href="/docs/introduction" />

      <Card icon="rocket" title="Quick Start" description="Create your first agent" href="/docs/getting-started/agent-creation" />

      <Card icon="sliders" title="Agent Setup" description="Configure your agents" href="/docs/agent-setup/overview" />

      <Card icon="code" title="API Reference" description="REST API documentation" href="/docs/api-reference/introduction" />
    </div>

    <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-sm">
      <a href="https://www.bolna.ai/docs/agents-library" className="font-medium text-gray-600 dark:text-zinc-400 hover:text-gray-900 dark:hover:text-zinc-200 no-underline">Agent Templates</a>
      <a href="https://www.bolna.ai/docs/platform-concepts" className="font-medium text-gray-600 dark:text-zinc-400 hover:text-gray-900 dark:hover:text-zinc-200 no-underline">Platform Concepts</a>
      <a href="https://platform.bolna.ai/" className="font-medium text-gray-600 dark:text-zinc-400 hover:text-gray-900 dark:hover:text-zinc-200 no-underline">Platform ↗</a>
    </div>
  </div>
</div>
