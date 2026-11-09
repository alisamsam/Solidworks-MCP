# Varjenci in razrez — uporabniški primeri

Stanje: 2026-10-19; 10 registriranih orodij.

[Začetni vodič](tools.md)

## Kako brati seznam

Vsaka vrstica poda primer, ki ga lahko napišeš agentu. To ni neposredni MCP/JSON
klic: agent pred izvedbo dopolni natančne mere, reference, datoteke in konfiguracijo.
Če jih ne more zanesljivo ugotoviti, vpraša. Zapis orodja je namenjen iskanju in
sledljivosti; imen si ni treba zapomniti.

**Učinek** je razred operacije iz registracije. »Pregled« ni splošno jamstvo, da
native API nikoli ne osveži podatkov (npr. razrezni seznam); glej mejo v vrstici.
Izvoz naredi datoteko, projektni poseg pa lahko vpliva na projektne reference.
Shranjevanje in zapiranje sta vedno izrecna dela naloge.

**Dokazi** pomenijo zgodovinske vpise iz registra zahtev:

- **P**: obstaja vpis o native/MCP preverjanju določene zahteve; ne vseh načinov orodja.
- **T**: v registru so samo enotski testi, brez potrjenega native preizkusa te zahteve.
- **O**: v registru obstaja neuspešen preizkus; preberi njegovo mejo in raje uporabi alternativo.
- **M**: mešani uspešni in neuspešni zapisi; potreben je pregled konkretnega primera.
- **—**: ni ločene povezane postavke v registru; to samo po sebi ne pomeni, da orodje ne deluje.

Registrirano ni isto kot trenutno omogočeno. Trenutni profil, zaščiteni način in
nameščeni dodatki lahko orodja skrijejo ali blokirajo; za trenutno stanje vprašaj
»Katera orodja so zdaj na voljo?«. Routing ostaja odložen in privzeto skrit.

| Orodje | Kaj mu naročiš | Učinek | Meja / potrebni podatki | Dokazi |
|---|---|---|---|---|
| `create_cosmetic_weld_bead` | Po teh robovih dodaj oznako zvara in izmeri njegovo dolžino. | sprememba modela | Kozmetični zvar ne doda materiala v prostornino ali maso. | P |
| `create_structural_member` | Iz črt te skice naredi varjenec z izbranim profilom. | sprememba modela | Več teles v enem partu; povezane črte se obravnavajo v skupini. | P |
| `create_weldment_end_cap` | Zapri ta odprti konec votlega profila s pokrovom. | sprememba modela | Potrebna je pravilna končna ploskev oziroma native zaznava konca. | P |
| `create_weldment_gusset` | Med tema profiloma dodaj ojačitveno ploščico. | sprememba modela | Telesi morata imeti dejanski skupni rob za podprti native spoj. | P |
| `get_cut_list` | Osveži in preberi razrezni seznam varjenca. | izbor/pogled/stanje | Bere native lastnosti; to še ni optimizacija nabavnega razreza. | — |
| `get_cut_list_body_map` | Pokaži, katera dejanska telesa pripadajo vsaki postavki razreza. | pregled | Brez osvežitve lastnosti; skrita telesa imajo drug indeksni kontekst. | P |
| `list_hole_wizard_sizes` | Pokaži velikosti izvrtin DIN ali ISO iz našega kataloga. | pregled | Katalog ne pomeni, da so bile vse velikosti geometrijsko preizkušene. | P |
| `list_weldment_profiles` | Pokaži profile, ki so že v naši knjižnici. | pregled | Uporabi obstoječe profile pred ustvarjanjem novih. | — |
| `save_bodies` | Izberi telesa tega varjenca in jih shrani kot povezane kose ter sestav. | sprememba modela | Čista shranjena kopija; native funkcija lahko shrani vir; brez prenosa lastnosti. | P |
| `trim_weldment_members` | Obreži ta dva člena, da dobita dogovorjeni stik. | sprememba modela | Preverjen miter stik z ničelno varilno režo. | P |
