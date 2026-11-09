"""Build/check Slovenian user guides against the actual registered MCP catalog.

No SolidWorks connection. Handwritten examples must cover every registered tool;
adding a tool requires adding its human-facing example before regeneration.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from solidworks_mcp.registry import registered_tools, operation_class_for
from solidworks_mcp.catalog import toolset_of

GROUPS={
    'sheetmetal':'Pločevina', 'weldments':'Varjenci in razrez',
    'assembly':'Sestavi, knjižnica in izbira kosov', 'project':'Projektne kopije in spremembe',
    'core':'Dokumenti, pregled, meritve in izvozi', 'features':'Volumensko modeliranje',
    'sketch':'Risanje skic', 'sketch_edit':'Urejanje in določanje skic',
    'drawing':'Tehnične risbe', 'surfaces':'Površine', 'planners':'Konceptni izračuni',
    'simulation':'Simulacije', 'routing':'Routing — odloženo področje',
}
OPS={'read':'pregled','stateful_read':'izbor/pogled/stanje','mutate':'sprememba modela',
     'export':'izhodna datoteka','project_write':'projektni poseg',
     'raw_execution':'surova koda','session':'seja programa'}
LEGEND='''
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
'''


def front(date,count,packaged=False):
    def link(group):
        return f'tools-{group}.md' if packaged else f'MCP-ORODJA-KATALOG.md#{group}'
    return f'''# SolidWorks MCP — uporabniški vodič

Stanje kataloga: **{date}; {count} registriranih orodij v {len(GROUPS)} skupinah**.
To je vodič za naročanje dela v slovenščini. Ni ti treba poznati imen ukazov,
pisati JSON ali naštevati vrstnega reda API klicev.

## Najkrajša uporabna zahteva

> Na naši kopiji [projekt/kos] naredi [spremembo] z merami [mere]. Pred posegom
> preveri pravi kos in reference, po njem preveri geometrijo ter pokaži rezultat.
> Izvirnikov ne spreminjaj.

Če kos ni jasen, najprej naroči **»Pripravi označen pregled tega kosa za odločitev.«**
Agent pridobi točno komponento, pripravi primeren prikaz in po potrebi vpraša.
Namesto dolgega imena lahko uporabljaš oznako iz dogovorjenega prikaza.

## Kaj lahko naročiš za svoje delo

| Želim | Primer naročila | Podrobnosti |
|---|---|---|
| Upognjena pločevina | Izdelaj pločevinasto polico 400 × 200 × 2 mm, z zavihoma 30 mm in radijem 2 mm. Najprej uskladi smer zavihov. | [Pločevina]({link('sheetmetal')}) |
| Več pločevin v enem partu | V isti part dodaj še drugo ločeno pločevinasto telo debeline 3 mm. Obstoječega ne spreminjaj. | [Pločevina]({link('sheetmetal')}) |
| Varjenec | Iz črt te skice naredi več členov v enem weldment partu. Najprej preveri našo knjižnico profilov. | [Varjenci]({link('weldments')}) |
| Stiki in ojačitve | Preveri stik teh dveh profilov; nato pripravi dogovorjeno obrezavo, pokrov ali ojačitev. | [Varjenci]({link('weldments')}) |
| Luknje | Na tej ploskvi naredi dogovorjene izvrtine po DIN ali ISO. Najprej pokaži razpoložljive velikosti. | [Modeliranje]({link('features')}) |
| Robovi za odločitev | Za T09 pripravi vse robove za odločitev v označenih pogledih. Modela še ne spreminjaj. | [Izbira kosov]({link('assembly')}) |
| Zaokrožitve/posnetja | Na dogovorjenih robovih tega parta naredi R2 oziroma posnetje 1 × 45°. Pred izvedbo preveri izbor. | [Modeliranje]({link('features')}) |
| Sestavljanje | V naši kopiji vstavi ta kos, preveri položaj in ga zveži z dogovorjenima ploskvama. | [Sestavi]({link('assembly')}) |
| Vijaki iz knjižnice | Pokaži razpoložljive vijake ISO 4017 M10 in nato vstavi izbrano dolžino. | [Knjižnica]({link('assembly')}) |
| Razrezni seznam | Osveži razrez varjenca in pokaži, katera telesa pripadajo vsaki postavki. | [Varjenci]({link('weldments')}) |
| Posamezni kosi iz teles | Iz teh teles naše čiste kopije pripravi povezane parte in sestav. Predhodno preveri izhodne poti. | [Save Bodies]({link('weldments')}) |
| DXF | Preveri razvitje tega kosa in ga izvozi v novo DXF datoteko za razrez. | [Pločevina]({link('sheetmetal')}) |
| DXF izbranega telesa | Iz tega večtelesnega parta izvozi samo dogovorjeno pločevino v DXF. Izvornega modela ne spreminjaj. | [Pločevina]({link('sheetmetal')}) |
| Tehnična risba | V pripravljeno risbo dodaj standardne poglede, ustrezne mere in razrezno tabelo. | [Risbe]({link('drawing')}) |
| Varna sprememba projekta | Naredi neodvisno kopijo projekta z vsemi referencami in delaj samo v njej. | [Kopije]({link('project')}) |
| Trki | Na naši kopiji preveri volumenske trke in naštej udeležene komponente. | [Pregled sestava]({link('project')}) |
| Koncept stopnic/ograje | Iz teh potrjenih mer pripravi koncept in posebej naštej manjkajoče podatke. | [Koncepti]({link('planners')}) |
| Nosilnost | Pripravi dogovorjeno študijo z navedenim materialom, vpetjem in obremenitvijo ter pokaži reakcije in pomike. | [Simulacije]({link('simulation')}) |

To so vzorci naročil, ne obljuba ene samodejne operacije za poljubno geometrijo.
Agent izbere dejansko omogočena orodja in preveri njihove podprte načine.

## Tri stvari, ki preprečijo nesporazume

1. **Pravi kos.** Povej projekt/revizijo in po potrebi pokaži mesto na sliki.
   Enako ime ne zagotavlja istega primerka. Pred spremembo se referenca preveri.
2. **Želeni rezultat.** Navedi mero in enoto ter stran/smer, kadar vpliva na kos.
   Pri predlogu s puščico ločimo obstoječi obris od želene spremembe.
3. **Kaj shraniti.** Povej, ali želiš samo pregled, spremembo naše kopije ali
   shranjen izhod. Tvojih neshranjenih sprememb nikoli ne zavržemo brez potrditve.

## Kaj trenutno ne smemo zamenjevati

- SVG za dogovor ni DXF za izdelavo. Trenutni SVG kaže en kos in uporablja
  oznake iste MCP seje; po restartu/spremembi modela pripravimo svež prikaz.
- Izbor roba komponente še ne omogoča poljubnega urejanja parta znotraj sestava.
- Več pločevinastih teles je podprtih; s tem še ni potrjen samodejen DXF vseh teles.
- Kozmetični zvar je oznaka/dolžina, ne dodan material ali nosilnost zvara.
- Razrezni seznam ni optimizacija nabavnih palic. Merjena geometrija ni sama
  po sebi obračunska ali nabavna količina.
- Uspešen izračun simulacije še ne potrdi pravilnih materialov, vpetij ali mreže.
- Routing/SN4: priključke in geometrijo beremo/urejamo v omejenem obsegu;
  prava samodejno generirana SN4 cev/trasa še ni dokončana. Razvoj je odložen.

## Celoten seznam po področjih

'''+ '\n'.join(f'- [{title}]({link(group)})' for group,title in GROUPS.items())+'''

V katalogu ima vsako orodje primer naročila, učinek, mejo in oznako zapisane
preverjenosti. Ta vodič ne izvaja CAD in ni nov preizkus vseh opisanih poti.
'''


def build(date):
    examples={}
    for line in (ROOT/'scripts/user_tool_examples.txt').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):continue
        name,prompt,note=(v.strip() for v in line.split('|'))
        if name in examples:raise ValueError('Duplicate example: '+name)
        examples[name]=(prompt,note)
    tools=sorted(registered_tools(),key=lambda t:t.name)
    names={t.name for t in tools}
    if names!=examples.keys():
        raise ValueError(f'Guide coverage mismatch; missing={sorted(names-examples.keys())}; extra={sorted(examples.keys()-names)}')
    rows=json.loads((ROOT/'scripts/capability_requirements.json').read_text(encoding='utf-8'))
    evidence=defaultdict(set)
    for row in rows:
        if row.get('tool_name'):evidence[row['tool_name']].add(row.get('verification_status','unknown'))
    def status(name):
        states=evidence[name]
        if 'current_live' in states and 'failed' in states:return 'M'
        if 'failed' in states:return 'O'
        if 'current_live' in states:return 'P'
        if 'unit_only' in states:return 'T'
        return '—'
    grouped=defaultdict(list)
    for tool in tools:
        group=toolset_of(tool.name)
        if group not in GROUPS:raise ValueError('Unknown guide group: '+str(group))
        prompt,note=examples[tool.name]
        op=operation_class_for(tool.name)
        grouped[group].append(f'| `{tool.name}` | {prompt} | {OPS[op.value]} | {note} | {status(tool.name)} |')
    header=f'# MCP orodja — celoten slovenski katalog\n\nStanje: {date}. **{len(tools)} orodij, {len(GROUPS)} skupin.**\n\n'
    header+='Začni z [uporabniškim vodičem](UPORABNISKI-VODIC.md).\n'+LEGEND+'\n## Področja\n\n'
    header+='\n'.join(f'- [{title} ({len(grouped[g])})](#{g})' for g,title in GROUPS.items())+'\n'
    catalog=header
    outputs={ROOT/'docs/UPORABNISKI-VODIC.md':front(date,len(tools))}
    workflow=ROOT/'solidworks_mcp/knowledge/solidworks-2025-expert/workflows'
    outputs[workflow/'tools.md']=front(date,len(tools),True)
    for group,title in GROUPS.items():
        table='| Orodje | Kaj mu naročiš | Učinek | Meja / potrebni podatki | Dokazi |\n|---|---|---|---|---|\n'+'\n'.join(grouped[group])+'\n'
        catalog+=f'\n<a id="{group}"></a>\n\n## {title} — {len(grouped[group])} orodij\n\n'+table
        outputs[workflow/f'tools-{group}.md']=f'# {title} — uporabniški primeri\n\nStanje: {date}; {len(grouped[group])} registriranih orodij.\n\n[Začetni vodič](tools.md)\n'+LEGEND+'\n'+table
    outputs[ROOT/'docs/MCP-ORODJA-KATALOG.md']=catalog
    snapshot=[dict(name=t.name,group=toolset_of(t.name),operation=operation_class_for(t.name).value,
                   description=t.description,schema=t.inputSchema) for t in tools]
    digest=hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    manifest=dict(as_of=date,registered_tools=len(tools),groups={g:len(grouped[g]) for g in GROUPS},
                  catalog_sha256=digest,tool_names=sorted(names),source='registry + scripts/user_tool_examples.txt + capability_requirements.json',
                  note='Registered definitions and recorded historical evidence; no live CAD test performed by this build.')
    outputs[ROOT/'docs/tool-guide-manifest.json']=json.dumps(manifest,ensure_ascii=False,indent=2)+'\n'
    return outputs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--date',default='2026-10-19')
    args=parser.parse_args();outputs=build(args.date);drift=[]
    for path,content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8')!=content:drift.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8')
    if drift:
        print('Outdated guides: '+', '.join(drift));return 1
    print(f'{"Checked" if args.check else "Generated"} {len(outputs)} guide files; all {len(registered_tools())} tools covered; no CAD connection.')
    return 0


if __name__=='__main__':raise SystemExit(main())
