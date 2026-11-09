# 10 MBD (Model-Based Definition) — navodila za obdelavo

## Opomba — izključeni moduli

**eDrawings (modul 22) je izključen.** Ne obravnavaj eDrawings workflowa za deljenje MBD podatkov.

Kadar se tema nanaša na eDrawings: "Ta funkcionalnost ni predmet tega workbooka, ker je modul eDrawings izključen."

## Kaj poudariti

- **PMI (Product and Manufacturing Information)** — kotiranje in toleranciranje neposredno na 3D modelu
- **3D Dimensions** — mere, dodane v 3D prostoru (ne na risbi)
- **GD&T v 3D** — geometrične tolerance neposredno na modelu
- **Datum Features** — referenčne točke/osi/ravnine za GD&T
- **DimXpert** — orodje za samodejno prepoznavanje in kotiranje funkcij
- **Annotation Views** — definirani pogledi, v katerih so PMI vidne (Front, Top, Right, ISO...)
- **Manufacturing Views** — pogledi, optimizirani za prikaz na delavnici
- **3D PDF export** — izvoz modela s PMI v 3D PDF format za deljenje brez eDrawings

## Obvezne usmeritve

- Razloži razliko med **MBD in 2D risbami**:
  - 2D risba: ločen dokument, kotiranje na pogledih, papirni ali PDF format
  - MBD: kotiranje na 3D modelu, brez ločene risbe, idealno za digitalno delavnico
  - MBD ne nadomesti risbe v vseh primerih — odvisno od kupca in industrije
- Pri **PMI** razloži uporabnost:
  - Meritve so vidne neposredno v 3D — delavec vidi model in mero hkrati
  - Primerno za kontrolo (CMM), montažo, dobavo
- Pri **DimXpert** razloži omejitve:
  - DimXpert samodejno prepozna izvrtine, navojnice, utore — a ne vedno pravilno
  - Vedno preveri avtomatsko prepoznane elemente in dopolni ročno
  - DimXpert shema ≠ ISO/ASME standard brez ročnega pregleda
- Pri **3D PDF** razloži:
  - 3D PDF je prenosljiv in ga lahko odpre Adobe Acrobat Reader (brezplačno)
  - Alternativa eDrawings workflowu (ki je izključen)
  - Primernost: za pošiljanje dobaviteljem, kupcem brez CAD programov
- Pri **standardih** omeniti razliko: ISO (mednarodni) vs. ASME (ameriški) GD&T standard — med njima so razlike v simbolih in interpretaciji toleranc

## Tipični primeri podtem

- PMI (Product and Manufacturing Information)
- 3D Dimensions in Annotations
- GD&T v 3D (Feature Control Frames)
- Datum Features v 3D
- DimXpert
- Annotation Views
- Manufacturing Views
- 3D PDF export
- Razlika MBD vs. 2D Drawing workflow
