# 09 Routing (Piping & Tubing) — navodila za obdelavo

## Opomba — izključeni moduli

**Electrical Routing (modul 16) je izključen.** Ne obravnavaj kabelskih tras, elektro kabelskih svežnjev, žic, konektorjev. Obravnavaj samo **piping** (cevovodi) in **tubing** (gibke cevi).

Kadar se tema nanaša na električni routing: "Ta funkcionalnost ni predmet tega workbooka, ker je modul Electrical izključen."

## Kaj poudariti

- **Routing Libraries** — knjižnica fitingov, flanšev, ventilov, spojk
- **Connection Points (CPoint)** — točke priključitve na fiting; definirajo smer in premer
- **Route Points (RPoint)** — vmesne točke poti; definirajo potek trase
- **Piping** — togi cevovodi z definiranimi standardnimi premeri
- **Tubing** — gibke cevi s krivuljami in minimalnimi radiji
- **Flexible Tubes** — posebna obravnava minimalnega radija krivljenja
- **Rigid Pipes** — togi segmenti med fiting točkami
- **Fittings** — fitingi iz knjižnice (T-kos, koleno, redukcija, flange)
- **Flanges** in **Elbows** — specifični elementi cevovoda
- **Auto Route** vs. **Manual Route**
- **Route BOM** — seznam materialov s prikazom dolžin cevi in fitingov
- **Spools** — konfiguracijska razdelitev cevovoda na dobavne enote

## Obvezne usmeritve

- Pri **CPoint in RPoint** razloži pomen:
  - CPoint definira **smer priključitve** in **nominalni premer** cevi — mora se ujemati s premerom cevi v trasi
  - RPoint definira **vmesno točko** poti — za ročno usmerjanje tras
  - Napačna smer ali premer CPointa = routing ne bo pravilno postavil cevi
- Pri **flexible tubes** razloži:
  - Minimalni radij krivljenja je materijalna lastnost cevi (npr. 5× premer)
  - Pod minimalnim radijem pride do prelamljanja ali prekorúpitve
  - SOLIDWORKS ne preverja samodejno minimalnega radija — inženir mora to preveriti ročno ali z analizo
- Pri **fittings** razloži:
  - Fitingi morajo biti v knjižnici Routing (ne gre za generične Part datoteke)
  - Vsak fiting mora imeti pravilno definirane CPoints
  - Brez knjižnice fitingov Routing ne deluje
- Pri **Route BOM** razloži:
  - BOM prikazuje: fiting, premer, dolžino cevi — na osnovi tega se naroča material
  - Dolžina cevi je skupna dolžina te-ga segmenta brez upoštevanja fitingov
- **Ne obravnavaj** electrical cabling, harness, žice, konektorjev, kabelskih omaric.

## Tipični primeri podtem

- Routing Library Management
- CPoint in RPoint definicija
- Auto Route
- Manual Route
- Piping (togi cevovodi)
- Tubing (gibke cevi)
- Fitting vstavljanje
- Flange in Elbow
- Route BOM
- Spools
- Routing risba
