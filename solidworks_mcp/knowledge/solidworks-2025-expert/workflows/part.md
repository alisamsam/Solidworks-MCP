# Parametrični del: načrt, skica, funkcije, preverjanje

Status: priporočeni postopek; celotna sekvenca še nima lastnega živega dokaza.
Razpoložljivost orodja in njegov posamičen test nista dokaz za ta model.

1. **Namera in parametri.** Določi funkcijo dela, ključne mere, material,
   orientacijo, simetrijo in predvidene spremembe. Ne privzemi manjkajoče
   montažne mere. Loči samostojen Part od več teles ali sestava.
2. **Načrt drevesa.** Izberi osnovni volumen in referenčne ravnine. Najprej
   stabilne reference in nosilna geometrija, nato funkcionalni rezi/luknje,
   ponovitve in zaključki. Zaokrožitev prestavi na konec, razen če njen
   radij določa naslednjo funkcionalno geometrijo. Zaporedje je odvisno od
   namere, ne univerzalni seznam klikov.
3. **Dokument in skica.** Preveri cilj, enote in ravnino. Ohrani dejansko ime
   skice. Dimenzije in relacije naj izrazijo namero; preveri
   get_sketch_relations. Popolnoma definirano ni sinonim za zgolj fiksirane
   entitete. Za ponovitve primerjaj vzorec funkcije in skice; veliko kopij
   geometrije v eni skici ni samoumevna prva izbira.
4. **Osnovna funkcija.** Zapri skico, izvedi eno operacijo, nato preveri novo
   funkcijo in mere/prostornino. Pri rezu preveri smer in dejanski odvzem
   materiala; skica na sredini kosa spremeni pomen enosmernega reza.
5. **Nadaljevanje.** Po spremembi ponovno pridobi ploskve/robove. Pred novo
   funkcijo preveri predpogoje. Ob neuspehu najprej preveri stanje dokumenta,
   šele nato popravljaj ali ponavljaj.
6. **Kontrola.** Primerjaj model s potrjenimi merami, številom teles in
   pričakovano geometrijo. Če imaš odobreno pot za spremembo parametra,
   preveri še spremembo mere in njene odvisnosti. Brez tega ne trdi, da je
   robustnost pri spremembah dokazana. Shrani/izvozi po uporabnikovem
   naročilu in pravilih izhodnih poti.

## Znane pasti

- Koordinate skice niso globalne. Na ploskvi ali zamaknjeni ravnini točke
  pretvori z ModelToSketchTransform; `create_sketch_on_face` ne vrne ključa
  skice, zato ime preberi iz `list_features`.
- Pri lastnem MathTransform nastavi ArrayData in jo preberi nazaj; tvorba
  transforma lahko tiho prezre vhod.
- Zdrava funkcija reza ne dokazuje pravilne strani odvzema. Preveri
  ohranjeno telo (volumen, bounding box), še posebej pri obrnjeni smeri.
- `create_reference_plane` zahteva točno ime ravnine (npr. "Right Plane");
  `create_sketch_on_plane` sprejme tudi kratko ime. Preberi `list_planes`.
- Zaokrožene vogale plošče raje nariši kot loke v osnovnem profilu kot
  fillet z izbiro roba po točki zaslona (izbor lahko ostane prazen).
- Samodejno popolno definiranje skice ne da kakovostnih kot za risbo;
  kote, ki nosijo namero, dodaj sam in jih veži na obstoječe parametre.
- Obstoječi parametri so vir mer: vrednost vzemi iz gradbene skripte ali
  zapisa dokaza in jo veži na skico, ne modeliraj znova.
- Na Top Plane kaže skicirna os Y v svetovno -Z (X ostane X). Točka s
  skicirnim y > 0 pristane pri z < 0. Pri Front Plane (X, Y) in Right
  Plane (Z, Y) ni obrata. Preveri z `get_body_bounding_box`.
- Dve nepovezani zanki (npr. pravokotnik in krog) v isti skici lahko dasta
  izvlek brez učinka ali samo z eno zanko. Raje vsako obliko v svojo skico
  ali eno skico z gnezdenimi zankami, nato preberi volumen.
- Skice za izvlek ne postavljaj na poševne ploskve: smer izvleka je
  normala ploskve. Ploščo ali ušesa nariši na standardni ravnini
  (Mid Plane izvlek) ali naredi vzporedno referenčno ravnino.

[Part Modeling](../references/modules/02-part-modeling.md)
