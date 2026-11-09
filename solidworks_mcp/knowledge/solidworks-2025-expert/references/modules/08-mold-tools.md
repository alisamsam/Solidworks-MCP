# 08 Mold Tools — navodila za obdelavo

## Opomba — izključeni moduli

**Plastics (modul 13) je izključen.** Ne obravnavaj simulacije brizganja, analize polnjenja kalupa, hladilnih kanalov ali časa strjevanja. Obravnavaj samo CAD pripravo geometrije kalupa.

Kadar se tema nanaša na simulacijo brizganja: "Ta funkcionalnost ni predmet tega workbooka, ker je modul Plastics izključen."

## Kaj poudariti

- **Draft Analysis** — preverjanje kotov odmika za odpiranje kalupa
- **Undercut Analysis** — odkrivanje negativnih kotov (nezahtevani podcutsi)
- **Thickness Analysis** — preverjanje debelin sten
- **Parting Line** — linija ločevanja med jedrom (core) in gnezdom (cavity)
- **Shut-off Surfaces** — površine za zapiranje lukenj skozi parting plane
- **Parting Surfaces** — razdelilne površine med core in cavity
- **Tooling Split** — končna delitev kalupnih plošč
- **Core/Cavity** — rezultat Tooling Split (dva ločena tridimenzionalna kosa)
- **Shrinkage Scale Factor** — kompenzacija krčenja materiala pri ohlajanju
- Priprava **uvoženega kosa** za mold workflow (čiščenje geometrije, dodajanje kotov odmika)

## Obvezne usmeritve

- Vedno razloži **smer odpiranja kalupa** — to je osnova vsega mold workflowa. Brez definirane smeri odpiranja ne moreš pravilno narediti Draft Analysis.
- Pri **Draft Analysis** razloži:
  - **Pozitivne površine** (zelen): kotirane v smeri odmika — v redu
  - **Negativne površine** (rdeč): problematične, kalup se ne bo odprl
  - **Nevtralne površine** (rumena): vzporedne s smerjo odmika
- Pri **Parting Line** razloži:
  - Parting Line razdeli površine na "core side" in "cavity side"
  - Napačna parting line = napačen core/cavity split
- Pri **Shut-off Surfaces** razloži:
  - Luknje (npr. za vijake, okna) skozi telo morajo biti zaprte, preden izvedemo tooling split
  - Shut-off površina mora biti G1 kontinuirana s sosednjimi površinami
- Pri **Tooling Split** jasno navedi:
  - Rezultat je CAD geometrija core in cavity plošč
  - To je **CAD priprava**, ne simulacija brizganja (Plastics je izključen)
- Pri **Shrinkage** razloži:
  - Vsak plastični material ima svojo stopnjo krčenja (npr. PP ~1.5%, ABS ~0.5%)
  - Scale Factor kompenzira krčenje tako, da kos po ohlajanju dobi pravo mero

## Tipični primeri podtem

- Draft Analysis
- Undercut Analysis
- Thickness Analysis
- Scale (Shrinkage)
- Parting Line
- Shut-off Surfaces
- Parting Surfaces
- Tooling Split
- Core in Cavity
- Priprava uvoženega modela za mold
