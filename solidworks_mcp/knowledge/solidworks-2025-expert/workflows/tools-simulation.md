# Simulacije — uporabniški primeri

Stanje: 2026-10-19; 8 registriranih orodij.

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
| `apply_fixed_fixture` | Te potrjene ploskve v študiji togo vpni. | sprememba modela | Fizična smiselnost vpetja mora biti določena. | P |
| `apply_force_load` | Na te ravne ploskve dodaj navedeno normalno silo ali podprti navor. | sprememba modela | Samo normalna sila na ravnih ploskvah; navor potrebuje referenčno os in izrecne enote. | P |
| `apply_pressure_load` | Na te ploskve dodaj tlak z izrecno navedeno enoto. | sprememba modela | Tlak ni skupna sila; pomembna sta površina in enota. | P |
| `create_static_study` | Za ta kos pripravi native statično študijo. | sprememba modela | Potreben ustrezen Simulation; pravilni material in robni pogoji so ločena naloga. | P |
| `get_displacement_results` | Preberi pomike rešene študije. | pregled | Določi komponento oziroma rezultanto in korak. | P |
| `get_reaction_results` | Preberi reakcije na vpetjih in primerjaj ravnovesje obremenitev. | pregled | Pri solid mreži native momentni del ne pomeni celotne fizične momentne reakcije. | P |
| `get_stress_results` | Preberi največje in najmanjše napetosti rešene študije. | pregled | Rezultat brez presoje singularnosti ni dovoljena obremenitev. | P |
| `run_analysis` | Ustvari mrežo in poženi pripravljeno študijo. | sprememba modela | Koda uspeha ne potrdi smiselnosti mreže ali robnih pogojev. | P |
