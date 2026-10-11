# Model maker logos

Shown on the admin console only, as a small tile beside a language model's name, to say who
made the model. Never on a client surface (D-679). Mapped to models in one place:
`apps/web/src/lib/modelLogos.ts`. A model whose maker is not listed there gets a monogram tile.

Files are committed unmodified and served from our own origin (`img-src 'self'`); nothing is
hot-linked. Trademarks remain their owners'.

## LobeHub Icons (MIT)

- Package: `@lobehub/icons-static-svg@1.95.1`, published 2026-09-21, tarball
  https://registry.npmjs.org/@lobehub/icons-static-svg/-/icons-static-svg-1.95.1.tgz
  (sha1 `7c6281bf457230b5cfc3b7c2cdd15d3b8d8ab479`), git head
  `49a2130df7bfa5eb1b088261bff20a37e2967789` of https://github.com/lobehub/lobe-icons.
- Licence: MIT (`package.json` `license`, and the repository's `LICENSE`, read 11 Oct 2026).
- Copied by hand from `package/icons/`. Not an npm dependency.

| File | Source path in the package | Maker | SHA-256 |
| --- | --- | --- | --- |
| `openai.svg` | `icons/openai.svg` | OpenAI | `a595df6b423920c67a7f8f73c063e4bfb72d415948097b6cac063a2366bb5186` |
| `qwen-color.svg` | `icons/qwen-color.svg` | Qwen (Alibaba) | `77f5768c66d08ce1d3d14e73373975c1bc0454be88c81523ddd0ffd7e2974029` |
| `gemini-color.svg` | `icons/gemini-color.svg` | Google Gemini | `8ab0a9bafec11f7e69bcb9fc4ffd8f1bc927d1ddcbbb6ff36dee5ae8b5a9d602` |
| `meta-color.svg` | `icons/meta-color.svg` | Meta (Llama) | `adf9f2c1a646ccd3a37ca8c2e7e5985d64630cd633f4b95fba393d1d44e0578c` |
| `deepseek-color.svg` | `icons/deepseek-color.svg` | DeepSeek | `deba5f98a5c1796e20fcac3149bcd7eb8a32f0bdd04d048819400b1f28bd1439` |
| `mistral-color.svg` | `icons/mistral-color.svg` | Mistral AI | `722f74b289d95486b43662fe24fa883b333701296f618406cd0ed502299170b6` |
| `claude-color.svg` | `icons/claude-color.svg` | Anthropic (Claude) | `a3101f3047a119aa11825ad9369510f0c472428c8c52d420e31bc62db44a8364` |
| `xai.svg` | `icons/xai.svg` | xAI (Grok) | `89eb7de9f0d02a41cfecd9109e253d7fd3529e27467dee4254faa67f3ac21451` |

## Makers not in LobeHub's set

| File | Source | Maker | SHA-256 |
| --- | --- | --- | --- |
| `thinnestai.png` | https://www.thinnest.ai/icon.png (the site icon its homepage links in `<link rel="icon">`), 32×37 PNG, read 11 Oct 2026 | ThinnestAI (Prana models) | `c34c1da586c4b375e79e70df3768f4a9e3eb0eb74f1594307568ffbc67f5e139` |

ThinnestAI publishes no brand page or logo licence (`/brand`, `/press` and `/media-kit` return
404). Its Terms of Service s.8 (https://www.thinnest.ai/legal/terms, read 11 Oct 2026) say its
branding is owned by Thinnest. We use the mark only to identify the maker of its own models on
our internal operator console, unaltered.

Replace a file only from the same kind of source, and update its row and hash here.
