/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/js/**/*.js",
  ],
  safelist: [
    "sm:grid-cols-2",  // dynamic :class in _modal_model_settings.html
    "max-w-[90rem]", "max-w-[100rem]", "max-w-none",  // dashboardWidthClass in dashboard_layout.js
    "bg-emerald-500", "text-white", "border-emerald-500",
    "bg-emerald-50", "text-emerald-700", "border-emerald-200", "hover:bg-emerald-100",
  ],
  theme: {
    extend: {
      fontFamily: {
        // System stack only, shared with the app (see tokens.json).
        sans: ['var(--font-sans)'],
      },
      colors: {
        surface: {
          DEFAULT: 'var(--bg-primary)',
          alt: 'var(--bg-secondary)',
          muted: 'var(--bg-tertiary)',
        },
        fg: {
          DEFAULT: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          tertiary: 'var(--text-tertiary)',
          muted: 'var(--text-muted)',
        },
        line: {
          DEFAULT: 'var(--border-faint)',
          strong: 'var(--border-normal)',
        },
        accent: {
          DEFAULT: 'var(--btn-primary)',
          hover: 'var(--btn-primary-hover)',
          fg: 'var(--btn-primary-text)',
        },
        danger: {
          DEFAULT: 'var(--text-danger)',
          bg: 'var(--bg-danger-hover)',
        },
        code: 'var(--code-bg)',
        // Apple system colours (tokens.json semantic.*), for status semantics.
        sys: {
          red: 'var(--sys-red)',
          orange: 'var(--sys-orange)',
          green: 'var(--sys-green)',
          blue: 'var(--sys-blue)',
        },
      },
      animation: {
        'fade-in-up': 'fadeInUp 0.5s ease-out forwards',
      },
      keyframes: {
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'none' },
        }
      }
    },
    // Exactly six type levels (tokens.json typography.scale). Replacing rather
    // than extending keeps off-scale sizes out of the utility set entirely;
    // the legacy Tailwind names stay as aliases so existing markup keeps
    // working while snapping onto the scale.
    fontSize: {
      xs: ['var(--fs-body)', { lineHeight: 'var(--lh-body)' }],
      sm: ['var(--fs-body)', { lineHeight: 'var(--lh-body)' }],
      base: ['var(--fs-emphasis)', { lineHeight: 'var(--lh-emphasis)' }],
      lg: ['var(--fs-emphasis)', { lineHeight: 'var(--lh-emphasis)' }],
      xl: ['var(--fs-section)', { lineHeight: 'var(--lh-section)' }],
      '2xl': ['var(--fs-page)', { lineHeight: 'var(--lh-page)' }],
      '3xl': ['var(--fs-kpi)', { lineHeight: 'var(--lh-kpi)' }],
      '4xl': ['var(--fs-kpi)', { lineHeight: 'var(--lh-kpi)' }],
      aux: ['var(--fs-aux)', { lineHeight: 'var(--lh-aux)' }],
      body: ['var(--fs-body)', { lineHeight: 'var(--lh-body)' }],
      emphasis: ['var(--fs-emphasis)', { lineHeight: 'var(--lh-emphasis)' }],
      section: ['var(--fs-section)', { lineHeight: 'var(--lh-section)' }],
      page: ['var(--fs-page)', { lineHeight: 'var(--lh-page)' }],
      kpi: ['var(--fs-kpi)', { lineHeight: 'var(--lh-kpi)' }],
    },
  },
  plugins: [],
}
