# Fonts

`Geist-Variable-latin.woff2` is the Latin subset of **Geist** by Vercel, a variable font
(weights 100 to 900; the app uses 400, 500 and 600). It is licensed under the
SIL Open Font License 1.1: https://github.com/vercel/geist-font

It is served by Streamlit's static file serving (`server.enableStaticServing` in
`.streamlit/config.toml`) and registered under `[[theme.fontFaces]]`, so the app needs no
internet connection for its font.
