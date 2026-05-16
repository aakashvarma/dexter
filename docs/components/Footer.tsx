import React from 'react'

type FooterProps = {
  menu?: boolean
}

export function Footer(_props: FooterProps) {
  return (
    <footer className="dexter-footer print:nx-hidden">
      <div className="dexter-footer-inner">
        <div className="dexter-footer-banner">
          <img
            src="/assets/images/dexter/footer-banner.png"
            alt=""
            className="dexter-footer-image"
          />
          <span className="dexter-footer-label">Dexter</span>
        </div>
        <p className="dexter-footer-tagline">Articulated Asset Agent System</p>
      </div>
    </footer>
  )
}
