# Arrissa Design Guide

## Colors

| Token        | Hex       | Usage                        |
|-------------|-----------|------------------------------|
| brand-500   | `#6366f1` | Primary actions, active nav  |
| brand-600   | `#4f46e5` | Buttons, hover states        |
| surface-950 | `#020617` | Page background              |
| surface-900 | `#0f172a` | Cards, sidebar               |
| surface-800 | `#1e293b` | Borders, table dividers      |
| surface-200 | `#e2e8f0` | Secondary text               |
| white       | `#ffffff` | Primary text, headings       |
| green-400   | —         | Active status, live env      |
| blue-400    | —         | Demo env tags                |
| red-400     | —         | Errors, destructive actions  |
| amber-400   | —         | Warnings, inactive status    |

## Typography

- **Font:** Inter (Google Fonts), fallback `system-ui, sans-serif`
- **Headings:** `font-semibold` or `font-bold`, white
- **Body:** `text-sm`, `text-surface-200`
- **Labels:** `text-xs font-medium text-surface-200`

## Icons

- **Library:** [Lucide](https://lucide.dev) — line icons only
- **Size:** `w-4 h-4` inline, `w-6 h-6` for empty states
- **Usage:** `<i data-lucide="icon-name" class="w-4 h-4"></i>`
- No emojis. Always use Lucide line icons.

## Layout

- **Sidebar:** Fixed, `w-60`, `bg-surface-900`, left-aligned
- **Main content:** `ml-60`, `px-8 py-6`
- **Top bar:** Sticky, blurred background, page title
- **Cards:** `bg-surface-900 border border-surface-800 rounded-xl`

## Components

### Buttons
- Primary: `bg-brand-600 hover:bg-brand-500 text-white rounded-lg`
- Secondary: `border border-surface-700 hover:border-surface-200 text-surface-200 rounded-lg`
- Destructive: `text-red-400 border border-surface-700 hover:border-red-800`

### Inputs
- `bg-surface-800 border border-surface-700 rounded-lg text-white`
- Focus: `focus:ring-2 focus:ring-brand-500 focus:border-transparent`

### Status badges
- `text-xs px-2 py-0.5 rounded-full font-medium`
- Active: `bg-green-900/40 text-green-400`
- Inactive: `bg-amber-900/40 text-amber-400`
- Demo: `bg-blue-900/40 text-blue-400 border border-blue-800`
- Live: `bg-green-900/40 text-green-400 border border-green-800`

### Alerts
- Success: `bg-green-900/30 border border-green-800 text-green-300`
- Error: `bg-red-900/30 border border-red-800 text-red-300`

## Sidebar Nav

```html
<a href="/route" class="sidebar-link active">
    <i data-lucide="icon" class="w-4 h-4"></i>
    Label
</a>
```

Active: `bg-brand-600/10 text-brand-400`
Inactive: `text-surface-200`, hover `bg-surface-800 text-white`

## Spacing

- Section gaps: `gap-6`
- Card padding: `p-5` or `px-5 py-4`
- Table cell padding: `py-3 px-5`

## Rules

1. Dark theme only.
2. No emojis — Lucide icons only.
3. Rounded corners: `rounded-lg` (inputs/buttons), `rounded-xl` (cards).
4. All interactive elements must have visible hover/focus states.
5. Keep pages uncluttered — one primary action per view.
