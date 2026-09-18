# Schach frontend — integration notes

Inspection of `https://github.com/ImpOrbTerr/Schach.git` (cloned as-is). No Schach source files were modified.

**Important mismatch:** this repository is **phpChess 4.2.1** (an AGPL PHP chess site, ~2004–2014), not a React/Vue/Next admin template. “Schach” is German for chess. There is no `package.json`, no SPA router, and no modern component library.

---

## 1. Framework / build tool / how to run locally

- **Framework:** server-rendered PHP with table-based HTML layouts. Pages set `$Contentpage` (e.g. `cell_admin_main.php`) and include a skin layout that injects that cell.
- **JS:** jQuery 1.7.1 + jQuery UI 1.8/1.10, Prototype/Scriptaculous (realtime chess UI), TinyMCE, Flexigrid.
- **Build tool:** none. No npm, Vite, webpack, or Composer.
- **Data:** MySQL (installer writes `bin/config.php`). `bin/config.txt` is empty until renamed/configured.
- **Dev run:** PHP + MySQL, not a Node port.
  1. From `frontend/`: `php -S localhost:8080`
  2. Rename `bin/config.txt` → `bin/config.php`
  3. Open `http://localhost:8080/install/` and follow the wizard
  4. Admin UI is under `/admin/` (entry: `admin/index.php`, home: `admin/admin_main.php`)

Default PHP built-in-server port used above: **8080**. There is no project-defined port.

---

## 2. Folder structure

| Path | Role |
|------|------|
| `index.php`, `chess_*.php` | Public chess site pages |
| `admin/` | Admin pages (login, players, games, billing, CMS, stats) |
| `includes/cells/` | Page body partials (`cell_*.php`) |
| `skins/default/` | Layouts, CSS, header/footer, left/right menus |
| `skins/default/layout_admin_cfg.php` | Admin chrome (header + left nav + content cell) |
| `bin/` | PHP classes and `config.php` |
| `includes/jquery/`, `includes/flexigrid/` | Vendor JS |
| `includes/tiny_mce/`, `includes/phpmailer/` | Editor / mail |
| `modules/` | Real-time chess interface |
| `install/` | First-run installer |
| `avatars/`, `skins/` | Static assets |

Routing is **one PHP file per page** (no client-side router).

---

## 3. Best base for a “Wind Site Suitability Dashboard”

Closest reusable shells (none are maps):

1. **`admin/admin_main.php` + `includes/cells/cell_admin_main.php` + `skins/default/layout_admin_cfg.php`** — admin dashboard chrome (sidebar + content). Best layout to clone for a new dashboard page.
2. **`admin/admin_player_list2.php` / `admin/admin_game_list.php`** — Flexigrid tables with Ajax paging. Best pattern for a ranked-sites results table.
3. **`admin/chess_statistics.php` / `includes/cells/cell_chess_statistics.php`** — stats-style content page (player stats, not analytics charts). Weak fit, but the only “analytics-like” page.

Recommended approach later: add a new admin page that reuses `layout_admin_cfg.php` and a new `cell_wind_suitability.php`, rather than stretching chess stats into GIS.

---

## 4. Mapping and charting libraries

- **Maps:** none. No Leaflet, Mapbox, Google Maps, or OpenLayers. TinyMCE has an incidental “Google maps” media comment only.
- **Charts:** none. No Chart.js, Recharts, ApexCharts, Highcharts, or Flot.
- **Tables:** Flexigrid for jQuery (XML/JSON Ajax grids) is already used on admin list pages.

Because this is PHP + jQuery (not React/Vue), **do not add React-Leaflet**. Next mapping step should be **Leaflet (vanilla JS)** plus a small chart library (e.g. Chart.js) loaded from CDN or `includes/`.
