# 19 Inspection — navodila za obdelavo

## Opomba — izključeni moduli

**PDM (modul 17) in Manage (modul 18) sta izključena.** Ne obravnavaj centralnega workflowa potrjevanja, PDM revizij, digitalnega podpisa prek Manage.

## Kaj poudariti

- **Ballooning** — številčenje karakteristik (karakteristika = mera ali zahteva za kontrolo)
- **Characteristic Extraction** — samodejno izvlecanje karakteristik iz risbe
- **Manual Characteristics** — ročno dodajanje karakteristik, ki jih samodejno ni prepoznal
- **Automatic Characteristics (OCR)** — zaznavanje karakteristik prek optičnega prepoznavanja iz PDF ali slika
- **Inspection Project** — organizacija karakteristik v projekt (First Article, Production)
- **Inspection Reports** — generiranje poročil v Excel, Word, PDF
- **FAI (First Article Inspection)** — postopek prvega vzorca
- **AS9102** — standard za FAI v letalski industriji
- **Custom Report Templates** — prilagojene predloge poročil
- **CMM Export** — izvoz karakteristik za koordinatno merilni stroj (Zeiss Calypso, PC-DMIS, Renishaw...)
- Povezava z **Drawings** in **MBD**

## Obvezne usmeritve

- Pri **OCR** opozori:
  - Samodejno prepoznavanje iz PDF/slike ni 100% zanesljivo
  - Vsako avtomatsko zaznano karakteristiko je treba ročno preveriti
  - Posebej problematično: tolerančna polja, GD&T simboli, drobni tekst
- Pri **ballooning** razloži pravilno številčenje:
  - Balonček vsebuje zaporedno številko karakteristike
  - Vsaka mera dobi svojo karakteristiko — ne smeš združevati mer v eno
  - Vzorec številčenja mora biti sistematičen (1, 2, 3...) za berljivo poročilo
- Pri **reports** razloži standardizacijo predlog:
  - Custom template omogoča: logotip, naslovna glava, oblika tabele, jezik
  - Predloge so shranjene kot Excel/Word osnove — prilagodljive
- Pri **revizijah** opozori:
  - Brez PDM/Manage ni centralnega upravljanja revizij in potrjevanja
  - Revizija v Inspection je samo vizualni marker v projektni datoteki
  - Ne obravnavaj PDM/Manage revizijskega workflowa
- Pri **CMM Export** razloži:
  - Karakteristike je mogoče izvoziti v strukturiran format za CMM programiranje
  - Preveriti kompatibilnost z vašim CMM sistemom (format izvoza se razlikuje)

## Tipični primeri podtem

- Ballooning (ročni, samodejni)
- Characteristic Extraction (samodejni iz risbe)
- OCR za PDF risbe
- Manual Characteristics
- Inspection Project setup
- FAI (First Article Inspection) workflow
- AS9102 standard
- Inspection Report generiranje
- Custom Report Templates
- CMM Export
- Povezava Inspection ↔ Drawing ↔ MBD
