import type { AppProps } from 'next/app'
import { Inter } from 'next/font/google'
import '../styles.css'

const inter = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-inter',
  display: 'swap',
})

export default function App({ Component, pageProps }: AppProps) {
  return (
    <div className={`${inter.variable} dexter-docs`}>
      <Component {...pageProps} />
    </div>
  )
}
