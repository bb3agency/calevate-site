# Page header

> A project page header that folds into a compact bar as you scroll, with tabs whose counts roll.

- Type: Block
- Page: https://uiarc.dev/components/blocks/page-header
- Markdown: https://uiarc.dev/components/blocks/page-header/markdown

- Access: Free, open source
- Registry id: `page-header`
- Source file: `registry/blocks/page-header/page-header.tsx`
- Built from: Button, Badge, Animated counter, Avatar group, Avatar, Progress
- Keywords: react page header, project header, sticky header on scroll, condensing header, record header with tabs, breadcrumb header, page title with actions

Use this at the top of a project, repository, or record page. Connect breadcrumbs to your router, tab counts and status to your data, and Follow, Share update, New issue, and Archive to your API; every action in the preview is simulated.

## When to use

- The top of a project, repository, or record page with breadcrumbs, status, people, and tabs.
- Detail pages with long content where the header should fold into a compact bar as people scroll.
- Headers that need a few primary actions plus an overflow menu for the rest.

## When not to use

- Use tabs and breadcrumb on their own when the page only needs navigation, not status and people.
- Use workspace-sidebar for app-level navigation between sections.
- Use settings-page for settings screens that need a section nav rather than a record header.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/page-header
pnpm dlx shadcn@latest add @uiarc/page-header
yarn dlx shadcn@latest add @uiarc/page-header
bunx --bun shadcn@latest add @uiarc/page-header
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/page-header.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react @radix-ui/react-tabs @radix-ui/react-dropdown-menu
```

2. Copy the source into your project. Main file: `registry/blocks/page-header/page-header.tsx`

   The source is in the registry item: https://uiarc.dev/r/page-header.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { PageHeader } from "@/components/arc/blocks/page-header/page-header";

export default function ProjectPage() {
  return (
    <main>
      <PageHeader />
    </main>
  );
}
```

## API reference

### PageHeader

A self-contained project header with breadcrumbs, status, members, progress, tabs and an actions menu that condenses into a compact bar on scroll. The project, people, tabs and counts are sample data declared at the top of page-header.tsx.

No props.

## Keyboard interactions

| Keys | Action |
| --- | --- |
| Arrow keys | Move between tabs (Radix tabs) and through the actions menu, which loops. |
| Enter / Space | Activates the focused tab or menu item. |

## Accessibility

- Tabs use Radix roles (tab, tabpanel) and the current breadcrumb carries aria-current.
- The icon-only actions trigger has aria-label="More actions"; disabled items use aria-disabled.
- A polite role="status" region announces results of Follow, Share, Copy link and Archive.

## Motion

- Past a short scroll threshold the header folds into a compact bar; the tab indicator glides with a shared layoutId and counts roll with Animated counter.
- Reduced motion swaps springs for fades, uses instant scroll instead of smooth, and keeps widths static.

## Responsive behavior

- A ResizeObserver moves secondary actions into the menu when the action row runs out of room.
- Below a 560px container the root breadcrumb hides, the tab row scrolls sideways with a faded edge, and below 460px the create button drops to an icon.
- The header condenses from the scroll of its own inner scroller, not the window, so page content must live inside that scroller.

## Performance

- Scroll handling only compares scrollTop to a 16px threshold, so it re-renders when crossing it, not on every frame.
- Tab counts roll with Animated counter and the tab indicator uses a shared layoutId; both are cheap at a handful of tabs.

## Notes for AI

- Use at the top of a project, repository or record page that scrolls beneath it.
- The block takes no props: replace the in-file project, people and tab data with your own, or lift them into props.
- Follow, Share update, Copy link, New issue and Archive are simulated; wire them to your API and the breadcrumbs to your router.
- Composes Arc Button, Badge, Animated counter, Avatar, Avatar group and Progress.

## Related

- [Tabs](https://uiarc.dev/components/tabs/markdown): Switch between related content in the same context.
- [Breadcrumb](https://uiarc.dev/components/breadcrumb/markdown): Show where a page sits in a hierarchy.
- [Avatar group](https://uiarc.dev/components/avatar-group/markdown): Show a team or set of contributors in a small space.
- [Dropdown menu](https://uiarc.dev/components/dropdown-menu/markdown): A focused list of actions anchored to a trigger.
- [Sidebar: Workspace](https://uiarc.dev/components/blocks/sidebar/markdown): A product sidebar with a workspace switcher, live search, draggable favorites, and inline projects.

## Guidance for AI tools

Blocks are complete, self-contained screens with sample data. Replace the sample data and connect the callbacks described above. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
