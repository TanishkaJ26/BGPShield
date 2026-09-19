# Hijax dashboard (plan Section 11, Phase 7)

A static Next.js site showing the measurements, built so it can be served from GitHub Pages
with no server at all.

## Where the data comes from

Nothing here queries anything at runtime. The pages read small JSON files under
`public/data/` **at build time**, so the measurements end up inside the HTML rather than being
fetched by the browser. That matters for this project: a page that is saved, archived or
printed has to still contain its numbers, and it should work with JavaScript switched off.

The one exception is the search box on the Networks page. That page renders its first hundred
rows into the HTML, and fetches the full megabyte-sized table only when somebody searches.

The JSON is written by the Python side:

```bash
uv run hijax adoption --export web/public/data/aspa_adoption.json
uv run hijax export
```

`hijax export` writes `summary.json`, `networks.json`, `regional.json`, `path_coverage.json`,
`longitudinal.json` and `incidents.json`. The whole set is kept under 5 MB, because these
files are committed and every clone of the repository pays for them.

Each file carries a `notes` field naming the limits that apply to its numbers. The pages
render those rather than hiding them, which is the point: the caveats are part of the
measurement, not a footnote.

## Building

```bash
npm install
npm run build          # static export into out/
```

For GitHub Pages, a project site is served from `/<repo>`, so set the base path:

```bash
NEXT_PUBLIC_BASE_PATH=/Hijax npm run build
```

`out/` is then a complete static site. Both `out/` and `node_modules/` are gitignored.

## A page with no data

If a JSON file is missing, the page says so and names the command that produces it. It never
shows a zero, because a zero reads as a measurement.
