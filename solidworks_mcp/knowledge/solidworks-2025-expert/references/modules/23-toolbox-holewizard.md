# 23 Toolbox & Hole Wizard — navodila za obdelavo

## Kaj poudariti

- **Hole Wizard** — ustvarjanje standardnih lukenj (navadne, navojne, counterbore, countersink, clearance)
- **Standardne luknje** — skladno z ISO/DIN/ANSI standardom
- **Navojne luknje** — Metric (M), UNC, UNF...
- **Clearance Holes** — luknje za prehod vijaka (Loose, Normal, Close Fit)
- **Counterbore** — poglabljanje za glavo vijaka (valj)
- **Countersink** — stožčasto poglabljanje za vgrezni vijak
- **Hole Callout** — samodejni opis luknje na risbi (standardiziran format)
- **Thread Feature** — modelirana navojna geometrija
- **Cosmetic Thread** — navidezni navoj (prikazano na risbi, ne modelirano v 3D)
- **Toolbox standardi** — knjižnica standardnih elementov (vijaki, matice, podložke, ležaji, zatiči...)
- **Smart Fasteners** — samodejno vstavljanje elementov Toolboxa v luknje sestava
- **Toolbox Configuration** — nastavitev knjižnice (lokacija, standardi, dostop)
- **Toolbox in BOM** — kako Toolbox elementi vplivajo na BOM

## Obvezne usmeritve

- Pri **Hole Wizard** razloži pomen standardov:
  - ISO standard: M luknje (M3, M4, M5, M6...)
  - DIN/ISO določa globino, premer vrtalnika, premer pri navojih
  - ANSI: UNC/UNF, inčni sistem
  - Napačen standard = napačen premer in globina = neizvedljivo v proizvodnji
- Pri **Hole Callout** razloži, zakaj je boljše uporabiti Hole Wizard kot navaden Extruded Cut:
  - Extruded Cut: luknja je brez standarda — ne prenese pravilnega Hole Callout na risbo
  - Hole Wizard: luknja vsebuje metadata (standard, tip, velikost) — Hole Callout samodejno in pravilno
  - Kontrolor v proizvodnji pričakuje standardni Hole Callout — navadni cut ga ne da
- Pri **Thread Feature** razloži razliko:
  - **Modelirani navoj**: geometrija navoja je dejansko v 3D — počasi, vizualno bogato, potrebno za CAM ali Visualize
  - **Cosmetic Thread**: navoj je označen s simbolno linijo v 3D in standardno oznako na risbi — hitro, zadostno za risbo
  - Za normalno inženirsko delo se priporoča Cosmetic Thread (razen za CAM)
- Pri **Toolbox** razloži vpliv konfiguracij na BOM:
  - Toolbox vijak je en Part z različnimi konfiguracijami (M6×20, M6×25, M8×30...)
  - V BOM-u se prikaže kot ena vrstica z opisom — konfiguracija določi oznako
  - Brez pravilno nastavljenega Toolboxa BOM ne bo pravilno prikazoval standardnih elementov
- Pri **deljenju datotek** opozori:
  - Toolbox je centralna knjižnica — brez PDM jo je treba ročno sinhronizirati med računalniki
  - Priporoča se skupna mrežna lokacija Toolboxa za vse v timu

## Tipični primeri podtem

- Hole Wizard (Countserbore, Countersink, Straight Tap, Tapered Tap, Clearance, Dowel Pin)
- Hole Callout na risbi
- Cosmetic Thread vs. Thread Feature
- Toolbox Library konfiguracija
- Smart Fasteners
- Vijaki, matice, podložke iz Toolboxa
- Ležaji, zatiči iz Toolboxa
- Toolbox in BOM
- Hole Series (za luknje skozi večdelni sestav)
