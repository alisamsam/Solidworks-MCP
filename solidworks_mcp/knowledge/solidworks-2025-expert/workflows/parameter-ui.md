# Parametri in namenski uporabniški vmesnik

Uporabi pri povezanih merah, variantah, ponavljajočih se revizijah ali zahtevi
po nastavljanju modela z obrazcem. Namen je zmanjšati napačne predpostavke
pred risanjem in uporabniku omogočiti razumljive spremembe po njem.

## Najprej stanje in konstrukcijska namera

1. Preberi razpoložljivo stanje dokumenta, konfiguracijo, parametre in
   povezane komponente. Loči obstoječi model od nove konstrukcije. Podatkov,
   ki jih lahko zanesljivo prebereš, ne sprašuj znova. Nedostopne podatke označi.
2. Z `mechanical-design-engineer`, če je na voljo, določi konstrukcijske
   odvisnosti in potrebne odločitve. Vprašaj v kratkih smiselnih skupinah:
   namen in način izdelave, referenčne mere, pritrditve, material in obdelava.
   Pojasni le vprašanja, pri katerih je referenca ali vpliv dvoumen.
3. Loči vhodne mere, izračunane mere, omejitve in uporabnikove preference.
   Predlog ni izmerjen podatek. Manjkajoče kritične mere ne nadomesti tiho
   z običajno vrednostjo; omogoči prazen vnos ali jasno označeno predpostavko.
4. Pred modeliranjem opiši zaporedje glavnih funkcij in odvisnosti.
   Izberi stabilne referenčne ravnine, glavne skice in poimenovane parametre,
   kjer jih razpoložljiva orodja podpirajo. Parametrizacija mora ohraniti
   namen konstrukcije pri spremembi, ne samo prvotnega videza.
5. Geometrijske mere spreminjaj samo prek podprtih orodij za mere/enačbe.
   Uporabniška lastnost (custom property) ne spremeni geometrije in ni
   nadomestek za spremembo mere.

## Obrazec prilagodi nalogi

Če gostitelj omogoča interaktivni prikaz, pripravi namenski obrazec. Če ga ne,
pripravi lokalno stran ali urejevalno tabelo z istimi podatki in jasno povej,
kako agent prejme spremembe. Obstoj HTML strani sam po sebi ni povezava z MCP.
Za novo integracijo je začetna možnost lokalna spletna nadzorna plošča ob
agentu; panel znotraj SolidWorksa zahteva ločeno integracijo.

- Prikaži ime modela in konfiguracijo ter stanje povezave.
- Polja poimenuj v uporabnikovem jeziku. Enote naj bodo vedno vidne.
  Uporabi številski vnos za mere, izbiro za profile/materiale in stikala za
  opcije. Drsnik dodaj le za smiseln omejen razpon in ohrani natančen vnos.
- Skupine prilagodi izdelku, npr. Geometrija, Profili, Pritrditev, Izdelava.
  Skrij tehnična imena API; prikaži jih le v diagnostiki.
- Izračunane vrednosti prikaži samo za branje z razlago odvisnosti.
  Prikaži trenutno prebrano vrednost in predlagano novo vrednost.
- Omejitve označi z izvorom. Priporočen razpon ni avtomatično predpis.
  Ob napaki ohrani vnos in pojasni, katera odvisnost ne ustreza.
- Shematski prikaz označi kot shemo; ne predstavljaj ga kot živi prikaz
  SolidWorks geometrije. Geometrijski predogled zahteva dejanske podatke CAD.

## Pogodba med poljem in modelom

Za vsako polje vzdržuj naslednje podatke; uporabniku pokaži samo koristne:

| Podatek | Namen |
|---|---|
| Stabilni ID, naziv, tip, enota | Nedvoumno razumevanje vnosa |
| Prebrana in predlagana vrednost, izvor | Ločevanje modela, meritve, uporabnikove zahteve in predpostavke |
| Vhodno / izračunano / nepodprto | Ali se sme neposredno urejati |
| Odvisnosti in omejitve z izvorom | Kaj se mora preračunati in zakaj |
| Dokument, konfiguracija, ciljna mera ali globalna spremenljivka | Natančna vezava na CAD, pridobljena iz modela |
| Nadrejeni sestav in pot konkretne pojavitve komponente | Razločevanje več vstavitev istega parta |
| Obseg spremembe in prizadete pojavitve | Preprečevanje nenamerne spremembe vseh instanc skupnega dela |
| Podprta operacija in pretvorba enot | Kako bo sprememba dejansko izvedena |
| Posnetek prejšnjega stanja in rezultat preverjanja | Zaznava zastarelega obrazca in dokaz spremembe |

Ne ugibaj imen, kot je `D1@Sketch1`. Če vezave ni, naj bo polje označeno kot
konstrukcijski vhod brez povezave z obstoječo mero. Ne pošiljaj poljubne kode
ali poti iz obrazca v izvajanje; obrazec naj pošlje tipizirane vrednosti
za vnaprej določene operacije.

### Lastnik parametra in skrite reference

Vsak parameter pripada projektu in konkretnemu lastniku: delu, sestavu,
pojavitvi komponente, telesu varjenca, risbi ali konstrukcijski zahtevi.
Za zahtevani, še neizdelani del je dovoljen načrtovani lastnik brez CAD vezave;
nikoli mu ne pripiši naključnega aktivnega dokumenta.

Uporabniku prikaži kratko pot, npr. »Stopnice → Ograja → Levi steber«.
Tehnične ID, datoteko, konfiguracijo, pot pojavitve, ciljno mero in revizijo
skrij pod »Podrobnosti«. Konfiguracijo in širši vpliv spremembe pokaži tudi
pred uporabo, kadar vplivata na rezultat. Skrite reference niso neobvezne.

Pojavitev komponente in skupni dokument dela sta različna cilja. Sprememba
geometrije istega parta v isti konfiguraciji lahko vpliva na vse njegove
pojavitve; z izbiro ene vrstice v drevesu je ne omejiš na eno pojavitev.
Za različno geometrijo ene pojavitve je potrebna ustrezna obstoječa konfiguracija
ali posebej dogovorjena nova konfiguracija/kopija. Ne ustvari je tiho.

Manjkajoča vrednost, izračunan parameter, nepovezana referenca in nepodprta
operacija so ločene oznake. Uporabniku povej, ali mora dopolniti podatek,
spremeniti izvorni vhod, obnoviti vezavo ali počakati na novo zmožnost.

### Zahteve in skupno stanje neodvisno od agenta

Obrazec in agent uporabljata isti projektni register; pogovor ni edini izvor
resnice. Pri vrnitvi v projekt najprej preberi register, čakajoče zahteve in
aktualno stanje modela. Ohrani uporabnikove osnutke ob osvežitvi CAD vrednosti.
Vnos »Spremeni višino tega stebra« shrani skupaj z izbranim lastnikom;
dvoumno besedilo razjasni pred izvajanjem. Brez povezanega agenta besedilna
zahteva ostane čakajoča in ne pomeni izvedenega ukaza.

Popravek najprej shrani kot projektno odločitev z razlogom in izvorom.
Splošno konstrukcijsko pravilo predlagaj ločeno z obsegom veljavnosti;
enkratnega popravka ne razglasi za pravilo vseh bodočih projektov.

Podrobna [specifikacija V1](../references/parameter-workspace-v1.md) določa
register, prikaze, vmesnike in sprejemne preizkuse. To je načrt novega
podsistema, ne seznam že implementiranih orodij. Preberi jo pri načrtovanju
ali preverjanju izvedbe V1, ne pri vsaki enostavni spremembi mere.

## Osnutek → preverjanje → uporaba → preverjen rezultat

Sprememba polja najprej spremeni osnutek. Ne izvajaj CAD mutacije pri vsakem
premiku drsnika. Prikaži predvidene spremembe in prizadete komponente.

Gumb »Uporabi v SolidWorksu« omogoči le, če obstaja dejanska povezava do
agenta/MCP in operacija za konkretno vezavo. Brez nje uporabi »Izvozi predlog«
ali obrazec jasno označi kot prototip. Preneseni JSON ni že uporabljena sprememba.

Ob uporabi:
1. Preveri tip, končnost števil, enote, dovoljene izbire in konstrukcijske
   odvisnosti na strani izvajalca, ne samo v brskalniku.
2. Ponovno preveri ciljni dokument, konfiguracijo in stare vrednosti. Če se
   model vmes spremeni, osveži obrazec in razreši konflikt pred zapisom.
3. Spremeni le izbrana vhodna polja v vrstnem redu odvisnosti. Med izvajanjem
   prepreči dvojno oddajo in sočasne mutacije istega modela.
4. Z razpoložljivimi operacijami obnovi model in preberi vrednosti nazaj.
   Preveri geometrijo, napake funkcij ter odvisne dele, vezi in risbo, kadar
   jih sprememba zadeva. Uspešen zapis vrednosti še ni uspešna konstrukcija.
5. Pokaži dejansko prebrane rezultate. Pri delni napaki navedi uspešne in
   neuspešne korake; ustavi nadaljnje odvisne mutacije. Ne obljubi atomarnosti
   ali povrnitve brez preverjene podpore. Obnovitveno kopijo uporabi, kadar
   je potrebna in podprta, znotraj dogovorjene politike shranjevanja.

Uporabnikovo navodilo ali klik Uporabi za konkretne spremembe je dovoljenje
znotraj dogovorjenega obsega; ne zahtevaj dodatne potrditve vsakega polja.
Shranjevanje izvirnih projektnih datotek ostaja ločena dogovorjena odločitev.

## Posebej: stopnice, ograje in cinkanje

Pri stopnicah najprej določi višino med dokončanima etažama, tlorisni prostor,
širino, podeste ter izbrano razdelitev. Število višin je celo število;
ne enači ga samodejno s številom nastopnih ploskev. Izbrana topologija določa
izračun. Višina posamezne enakomerne stopnice je odvisna od skupne višine
in števila višin. Razjasni debeline zaključnih slojev in referenco merjenja.

Stopnišno ograjo veži na dejansko linijo stopnic, podeste in montažne odmike.
Razjasni, od kod in v kateri smeri merimo višino ograje; navpični in pravokotni
odmik od poševne linije nista ista mera. Višina ograje, razmiki stebrov,
polnila in sidranje potrebujejo konstrukcijska pravila za konkretno uporabo.
S spremembo stopnic ponovno preveri povezano ograjo in njene prehode.

Izbira vročega cinkanja sproži ustrezna navodila konstrukterskega skilla:
votli prostori, odzračevanje, iztok, orientacija in delitev za obdelavo.
Stikalo »cinkanje« samo po sebi ne potrjuje primernosti izdelka. Odprtin in
njihovih mer ne določi brez ustreznega vira in geometrijskega preverjanja.

## Trenutna meja podpore in naslednja izvedbena faza

Prvi del registra in lokalnega spletnega vmesnika je implementiran 26. 9. 2026.
`read_parameter_workspace` prebere projekte oziroma register projekta.
`write_parameter_workspace` spreminja samo register: lastnike, definicije,
osnutke in zahteve. Ne spreminja CAD. Pred zapisom preberi aktualno revizijo
in jo posreduj kot `expected_revision`.
Pri branju loči `has_draft=false` od osnutka z `draft_value=null`: slednji
pomeni izrecno prazen vnos. Za vrnitev na evidentirano vrednost uporabi
`discard_draft`. Konflikta ne obidi s slepim ponavljanjem zapisa brez revizije.
Najprej preberi obe vrednosti in uskladi uporabnikovo namero. `calculation_error`
razloži napako preračuna; ne označi je zgolj kot manjkajočo uporabnikovo mero.
Čakajoča zahteva potrebuje agenta; stran sama ne zbudi poljubnega harnessa.
CAD zajem in izvajalni adapterji
ostajajo naslednja faza. Za točne argumente in zagon preberi
[operativno pogodbo registra](../references/parameter-workspace-operations.md),
MCP topic `reference/parameter-workspace-operations`.

Vedno preveri aktualne MCP sheme. V pregledu izvorne kode 25. 9. 2026
`add_equation` dodaja globalno spremenljivko; ni splošno orodje za spremembo
obstoječe mere ali enačbe. `add_sketch_dimension` ustvarja mero;
`set_custom_property` spreminja metapodatke. Nobenega ne uporabi kot navidezno
zamenjavo za urejanje že vezane geometrijske mere. Od 26. 9. sta na voljo
`list_model_parameters` in `set_model_dimension`; operativne pogoje in
preverjene omejitve preberi v [kopiranju projekta](project-copy.md).
To še ne predstavlja samodejnega adapterja spletnega GUI.

Za povezano nadzorno ploščo potrebujemo preverjeno pot:
obrazec → tipiziran zahtevek → preverjanje cilja in vezave v MCP → sprememba
parametrov → obnova in branje rezultata → prikaz dejanskega stanja.
To je razvojna zahteva, ne trditev, da ta celotna pot že obstaja.

Najprej preveri celoten krog na preprostem poskusnem delu z nekaj vhodnimi
merami in eno odvisno mero. Preizkusi tudi napačne enote, zastarelo stanje,
neuspešno obnovo in dvojni klik. Šele nato razširi na stopnice in ograje.
Za to začetno fazo ni potrebno učenje modela iz videoposnetkov; pomembni so
zanesljive vezave, konstrukcijske odvisnosti in preverjanje vsake spremembe.


## Izvajalni adapter — 26. 9. 2026

Aktualni postopek je `workflow/engineering-package`: uvoz obstoječih mer
z `import_parameter_workspace`, osnutki in čakalna vrsta v GUI, nato
`process_parameter_workspace_job` prek MCP. Oddaja v GUI ne izvede CAD zapisa.
Omejitve starejšega pregleda spodaj so zgodovinske; razpoložljivost konkretne
operacije preveri v aktualni shemi.
