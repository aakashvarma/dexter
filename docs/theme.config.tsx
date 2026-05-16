import React from 'react'
import { DocsThemeConfig } from 'nextra-theme-docs'
import { Footer } from './components/Footer'

const config: DocsThemeConfig = {
  logo: (
    <span className="dexter-logo">
      <strong>Dexter</strong> Docs
    </span>
  ),
  project: {
    link: 'https://github.com/aakashvarma/dexter',
  },
  docsRepositoryBase: 'https://github.com/aakashvarma/dexter/tree/main/docs',
  footer: {
    component: Footer,
    text: '',
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
