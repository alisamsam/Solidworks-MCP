# 20 Composer — navodila za obdelavo

## Kaj poudariti

- **Import CAD modelov** — uvoz SOLIDWORKS, STEP, IGES, OBJ... v Composer
- **Update CAD Data** — posodobitev dokumentacije ko se model v SolidWorksu spremeni
- **Actors** — vse komponente v Composerju so "actors" (objekti, ki jih animiraš in pozicioniraš)
- **Views** — shranjene pozicije kamer, vidnost komponent, eksplozijsko stanje
- **Exploded Views** — vizualni razpad sestava za montažna navodila
- **Callouts** — napisi, oznak, puščice na komponentah
- **BOM v Composerju** — avtomatski seznam materialov iz uvoženih metapodatkov
- **Annotations** — tehnični napisi, mere (vizualni, ne CAD mere)
- **Technical Illustrations** — vektorske ali rastrske ilustracije za priročnike
- **Vector Output** — SVG, EPS — primerno za tisk in tehnično dokumentacijo
- **Raster Output** — PNG, JPG — primerno za splet, kataloge
- **Animations** — sekvence za montažna in servisna navodila
- **Service Instructions** — servisni priročniki korak za korakom
- **Assembly Instructions** — montažna navodila z eksplozijami in komentarji
- **Spare Parts Catalogs** — katalogi rezervnih delov

## Obvezne usmeritve

- Pri **uvozu CAD podatkov** razloži pomen pripravljene strukture sestava:
  - Composer bere strukturo sestava iz SolidWorksa (hierarhija, custom properties, konfiguracije)
  - Slabo organiziran sestav = slabo organizirana Composer dokumentacija
  - Priporoča se čiščenje sestava pred uvozom: pravilna imenovanja, custom properties
- Pri **Update CAD Data** razloži:
  - Ko se model v SolidWorksu posodobi, Composer zazna razlike pri uvozu
  - Stare views se ohranijo, nova geometrija se posodobi — toda treba je preveriti, ali so se komponente premaknile
  - Update ne more samodejno "popraviti" dokumentacije — inženir mora preveriti vsako stran
- Pri **views** razloži:
  - View = shranjeno stanje (pozicija kamere, vidnost, eksplozija, callouts)
  - Vsak korak montažnih navodil = en view
  - Prek Tech Doc (sekvencer) se views sestavijo v sekvenco navodil
- Pri **output formatih** razloži razliko:
  - **SVG/EPS**: vektorski — skalabilen brez izgube kakovosti, primeren za tisk in PDF
  - **PNG/JPG**: rastrski — fiksna resolucija, primeren za splet, kataloge, presentacijo
- Pri **animacijah** razloži:
  - Animacija v Composerju je sekvenca views + prehodov
  - Primerna za montažna in servisna navodila z gibanjem (ne za fizikalno simulacijo)

## Tipični primeri podtem

- Import CAD v Composer
- Update CAD (spremembe modela)
- Views in View organizacija
- Exploded View v Composerju
- Callouts in Annotations
- BOM v Composerju
- Technical Illustration (vektorski in rastrski output)
- Animation in Tech Doc sekvencer
- Assembly Instructions workflow
- Service Instructions workflow
- Spare Parts Catalog
- Integracijska pot SOLIDWORKS → Composer → PDF priročnik
