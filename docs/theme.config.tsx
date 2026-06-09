import React from 'react'
import { DocsThemeConfig } from 'nextra-theme-docs'

const config: DocsThemeConfig = {
  logo: <span><strong>Dexter</strong> Docs</span>,
  project: {
    link: 'https://github.com/aakashvarma/dexter',
  },
  docsRepositoryBase: 'https://github.com/aakashvarma/dexter/tree/main/docs',
  footer: {
    text: 'Dexter — Articulated Asset Agent System',
  },
  primaryHue: 210,
  sidebar: {
    defaultMenuCollapseLevel: 1,
  },
  useNextSeoProps() {
    return {
      titleTemplate: '%s – Dexter'
    }
  },
}

export default config
